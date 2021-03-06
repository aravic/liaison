"""Graphnet based model."""

import graph_nets as gn
import numpy as np
import sonnet as snt
from liaison.agents.models.utils import *
from liaison.agents.utils import *
from sonnet.python.ops import initializers

INF = np.float32(1e9)

EDGE_BLOCK_OPT = {
    "use_edges": True,
    "use_receiver_nodes": True,
    "use_sender_nodes": True,
    "use_globals": True
}

NODE_BLOCK_OPT = {
    "use_received_edges": True,
    "use_sent_edges": False,
    "use_nodes": True,
    "use_globals": True,
}

GLOBAL_BLOCK_OPT = {
    "use_edges": False,
    "use_nodes": False,
    "use_globals": True,
}


def make_mlp(layer_sizes,
             activation,
             activate_final,
             seed,
             layer_norm=False,
             **kwargs):
  mlp = snt.nets.MLP(layer_sizes,
                     initializers=dict(w=glorot_uniform(seed),
                                       b=initializers.init_ops.Constant(0)),
                     activate_final=activate_final,
                     activation=get_activation_from_str(activation),
                     **kwargs)
  if layer_norm:
    return snt.Sequential([mlp, snt.LayerNorm()])
  else:
    return mlp


class Model:

  def __init__(
      self,
      seed,
      activation='relu',
      n_prop_layers=4,
      edge_embed_dim=32,
      node_embed_dim=32,
      global_embed_dim=8,
      node_hidden_layer_sizes=[64],
      edge_hidden_layer_sizes=[32],  # if num edges is high keep this light.
      policy_summarize_hidden_layer_sizes=[32],
      value_summarize_hidden_layer_sizes=[32],
      policy_torso_hidden_layer_sizes=[64, 64],
      value_torso_hidden_layer_sizes=[64, 64],
      supervised_prediction_torso_hidden_layer_sizes=[64, 64],
      action_spec=None,
      sum_aggregation=True,
      use_layer_norm=True,
      **kwargs):
    self.activation = get_activation_from_str(activation)
    self.n_prop_layers = n_prop_layers
    self.seed = seed
    self.policy = None
    self.value = None
    self.edge_embed_dim = edge_embed_dim
    self.node_embed_dim = node_embed_dim
    self.global_embed_dim = global_embed_dim

    with tf.variable_scope('encode'):

      def f(embed_dim, name):
        return make_mlp([embed_dim] * 2,
                        activation,
                        activate_final=True,
                        seed=seed,
                        layer_norm=False,
                        name=name)

      self._var_encode_net = f(node_embed_dim, 'var_encode_net')
      self._constraint_encode_net = f(node_embed_dim, 'constraint_encode_net')
      self._obj_encode_net = f(node_embed_dim, 'obj_encode_net')

      self._encode_net = gn.modules.GraphIndependent(
          edge_model_fn=lambda: f(edge_embed_dim, 'edge_encode'),
          global_model_fn=lambda: f(global_embed_dim, 'global_encode'),
          node_model_fn=lambda: f(node_embed_dim, 'node_encode'))

    with tf.variable_scope('edge_model'):
      edge_model = make_mlp(edge_hidden_layer_sizes + [edge_embed_dim],
                            activation,
                            activate_final=True,
                            seed=seed,
                            layer_norm=use_layer_norm)
    with tf.variable_scope('node_model'):
      node_model = make_mlp(node_hidden_layer_sizes + [node_embed_dim],
                            activation,
                            activate_final=True,
                            seed=seed,
                            layer_norm=use_layer_norm)

    self._graphnet_models = [None for _ in range(n_prop_layers)]
    for i in range(n_prop_layers):
      with tf.variable_scope('graphnet_model_%d' % i):
        # global(node(edge))
        self._graphnet_models[i] = gn.modules.GraphNetwork(
            edge_model_fn=lambda fn=edge_model: fn,
            node_model_fn=lambda fn=node_model: fn,
            global_model_fn=lambda: lambda x:
            x,  # Don't summarize nodes/edges to the globals.
            # if this is modified, add residual connections for globals as well.
            node_block_opt=NODE_BLOCK_OPT,
            edge_block_opt=EDGE_BLOCK_OPT,
            global_block_opt=GLOBAL_BLOCK_OPT,
            reducer=tf.unsorted_segment_sum
            if sum_aggregation else tf.unsorted_segment_mean)

    with tf.variable_scope('policy_torso'):
      self.policy_torso = snt.nets.MLP(
          policy_torso_hidden_layer_sizes + [1],
          initializers=dict(w=glorot_uniform(seed),
                            b=initializers.init_ops.Constant(0)),
          activate_final=False,
          activation=self.activation)

    with tf.variable_scope('supervised_prediction_torso'):
      self.supervised_prediction_torso = snt.nets.MLP(
          supervised_prediction_torso_hidden_layer_sizes + [1],
          initializers=dict(w=glorot_uniform(seed),
                            b=initializers.init_ops.Constant(0)),
          activate_final=False,
          activation=self.activation,
      )

    with tf.variable_scope('policy_summarize'):
      self.policy_summarize = snt.nets.MLP(
          policy_summarize_hidden_layer_sizes,
          initializers=dict(w=glorot_uniform(seed),
                            b=initializers.init_ops.Constant(0)),
          activate_final=True,
          activation=self.activation,
      )

    with tf.variable_scope('value_summarize'):
      self.value_summarize = snt.nets.MLP(
          value_summarize_hidden_layer_sizes,
          initializers=dict(w=glorot_uniform(seed),
                            b=initializers.init_ops.Constant(0)),
          activate_final=True,
          activation=self.activation,
      )

    with tf.variable_scope('value_torso'):
      self.value_torso_2 = snt.nets.MLP(
          value_torso_hidden_layer_sizes + [1],
          initializers=dict(w=glorot_uniform(seed),
                            b=initializers.init_ops.Constant(0)),
          activate_final=False,
          activation=self.activation,
      )

  def _validate_observations(self, obs):
    for k in [
        'graph_features', 'node_mask', 'var_type_mask', 'constraint_type_mask',
        'obj_type_mask'
    ]:
      if k not in obs:
        raise Exception('%s not found in observation.' % k)

  def _encode(self, graph_features: gn.graphs.GraphsTuple, var_type_mask,
              constraint_type_mask, obj_type_mask):
    nodes = graph_features.nodes
    node_indices = gn.utils_tf.sparse_to_dense_indices(graph_features.n_node)
    l = [var_type_mask, constraint_type_mask, obj_type_mask]
    for i, mask in enumerate(l):
      mask = tf.reshape(mask, [-1, tf.shape(mask)[-1]])
      l[i] = tf.gather_nd(params=mask, indices=node_indices)
    var_type_mask, constraint_type_mask, obj_type_mask = l

    # TODO(arc): remove feature padding from nodes.
    nodes = tf.where(
        tf.equal(var_type_mask, 1), self._var_encode_net(nodes),
        tf.where(tf.equal(constraint_type_mask, 1),
                 self._constraint_encode_net(nodes),
                 self._obj_encode_net(nodes)))
    col = tf.fill([infer_shape(nodes)[0]], 0)
    node_types = tf.where(
        tf.equal(var_type_mask, 1), col,
        tf.where(tf.equal(constraint_type_mask, 1), col + 1, col + 2))
    node_types = tf.one_hot(node_types, 3)
    nodes = tf.concat([nodes, node_types], axis=-1)
    graph_features = graph_features.replace(nodes=nodes)
    graph_features = self._encode_net(graph_features)
    return graph_features

  def _convolve(self, graph_features: gn.graphs.GraphsTuple):
    for i in range(self.n_prop_layers):
      with tf.variable_scope('prop_layer_%d' % i):
        # one round of message passing
        new_graph_features = self._graphnet_models[i](graph_features)
        # residual connections
        graph_features = graph_features.replace(
            nodes=new_graph_features.nodes + graph_features.nodes,
            edges=new_graph_features.edges + graph_features.edges,
            # residual connection not needed for globals,
            # since the current global_model_fn is identity
            globals=new_graph_features.globals)

    return graph_features

  def _attn_convolve(self, graph_features: gn.graphs.GraphsTuple):

    num_heads = self.config.num_heads
    key_size = self.config.key_size
    value_size = self.config.node_embed_dim

    for i in range(self._n_prop_layers):
      with tf.variable_scope('attention'):
        nodes = graph_features.nodes
        qkv_size = 2 * key_size + value_size
        # total_size = qkv_size * num_heads  # denote as F

        # [total_num_nodes, d] => [total_num_nodes, F]
        qkv_flat = self._attention_dense_layers[i](nodes)

        qkv = tf.reshape(qkv_flat, [-1, num_heads, qkv_size])
        # q => [total_num_nodes, num_heads, key_size]
        # k => [total_num_nodes, num_heads, key_size]
        # v => [total_num_nodes, num_heads, value_size]
        q, k, v = tf.split(qkv, [key_size, key_size, value_size], -1)

      with tf.variable_scope('prop_layer_%d' % i):
        new_graph_features = self._graphnet_models[i](v, k, q, graph_features)
        # residual connections
        graph_features = graph_features.replace(
            nodes=new_graph_features.nodes + graph_features.nodes,
            edges=new_graph_features.edges + graph_features.edges,
            globals=new_graph_features.globals + graph_features.globals)

  def compute_graph_embeddings(self, obs):
    self._validate_observations(obs)
    # Run multiple rounds of graph convolutions
    graph_features = self._convolve(
        self._encode(obs['graph_features'], obs['var_type_mask'],
                     obs['constraint_type_mask'], obs['obj_type_mask']))
    return graph_features

  def get_node_embeddings(self, obs):
    graph_features = self.compute_graph_embeddings(obs)
    graph_features = graph_features.replace(globals=tf.concat([
        graph_features.globals,
        gn.blocks.NodesToGlobalsAggregator(tf.unsorted_segment_mean)
        (graph_features.replace(
            nodes=self.policy_summarize(graph_features.nodes)))
    ],
                                                              axis=-1))

    graph_features = graph_features.replace(nodes=tf.concat([
        graph_features.nodes,
        gn.blocks.broadcast_globals_to_nodes(graph_features)
    ],
                                                            axis=-1))
    return graph_features.nodes

  def get_logits(self, graph_features: gn.graphs.GraphsTuple, node_mask):
    """
      graph_embeddings: Message propagated graph embeddings.
                        Use self.compute_graph_embeddings to compute and cache
                        these to use with different network heads for value, policy etc.
    """
    # broadcast globals and attach them to node features
    graph_features = graph_features.replace(globals=tf.concat([
        graph_features.globals,
        gn.blocks.NodesToGlobalsAggregator(tf.unsorted_segment_mean)
        (graph_features.replace(
            nodes=self.policy_summarize(graph_features.nodes)))
    ],
                                                              axis=-1))

    graph_features = graph_features.replace(nodes=tf.concat([
        graph_features.nodes,
        gn.blocks.broadcast_globals_to_nodes(graph_features)
    ],
                                                            axis=-1))
    # get logits over nodes
    logits = self.policy_torso(graph_features.nodes)
    # remove the final singleton dimension
    logits = tf.squeeze(logits, axis=-1)
    log_vals = {}
    # record norm *before* adding -INF to invalid spots
    log_vals['opt/logits_norm'] = tf.linalg.norm(logits)

    indices = gn.utils_tf.sparse_to_dense_indices(graph_features.n_node)
    logits = tf.scatter_nd(indices, logits, tf.shape(node_mask))
    logits = tf.where(tf.equal(node_mask, 1), logits,
                      tf.fill(tf.shape(node_mask), -INF))
    return logits, log_vals

  def get_auxiliary_loss(self, graph_features: gn.graphs.GraphsTuple, obs):
    """
      Returns a prediction for each node.
      This is useful for supervised node labelling/prediction tasks.
    """
    node_mask = obs['node_mask']
    # broadcast globals and attach them to node features
    graph_features = graph_features.replace(nodes=tf.concat([
        graph_features.nodes,
        gn.blocks.broadcast_globals_to_nodes(graph_features)
    ],
                                                            axis=-1))
    # get logits over nodes
    logits = self.supervised_prediction_torso(graph_features.nodes)
    # remove the final singleton dimension
    logits = tf.squeeze(logits, axis=-1)
    indices = gn.utils_tf.sparse_to_dense_indices(graph_features.n_node)
    preds = tf.scatter_nd(indices, logits, tf.shape(node_mask))

    var_type_mask = obs['var_type_mask']
    auxiliary_loss = tf.reduce_mean(
        tf.boolean_mask((preds - obs['optimal_solution'])**2,
                        tf.cast(var_type_mask, tf.bool)))
    return auxiliary_loss

  def get_value(self, graph_features: gn.graphs.GraphsTuple):
    """
      graph_embeddings: Message propagated graph embeddings.
                        Use self.compute_graph_embeddings to compute and cache
                        these to use with different network heads for value, policy etc.
    """
    with tf.variable_scope('value_network'):
      agg = gn.blocks.NodesToGlobalsAggregator(tf.unsorted_segment_mean)(
          graph_features.replace(
              nodes=self.value_summarize(graph_features.nodes)))

      value = tf.concat([agg, graph_features.globals], axis=-1)
      return tf.squeeze(self.value_torso_2(value), axis=-1)

  def dummy_state(self, bs):
    return tf.fill(tf.expand_dims(bs, 0), 0)

  def get_initial_state(self, bs):
    return self.dummy_state(bs)
