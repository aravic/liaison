"""Shell for policy evaluation.

Env variables used:
  SYMPH_PS_FRONTEND_HOST
  SYMPH_PS_FRONTEND_PORT
"""

import copy
import os

import tensorflow as tf
from absl import logging
from liaison.distributed import ParameterClient
from liaison.env import StepType
from liaison.specs import ArraySpec
from liaison.utils import ConfigDict
from tensorflow.contrib.framework import nest


class SyncNever:

  def should_sync(self, *args):
    return False


class SyncEveryNSteps:

  def __init__(self, sync_period):
    self.sync_period = sync_period

  def should_sync(self, step):
    return step % self.sync_period == 0


class Shell:
  """
  Shell has the following tasks.

  (1) Create a TF Agent graph.
  (2) Extract the learnable exposed weights from the TF graph.
  (3) Connect to parameter server and sync the weights regularly.
  """

  def __init__(
      self,
      action_spec,
      obs_spec,
      seed,
      # Above args provided by actor.
      agent_class,
      agent_config,
      batch_size,
      agent_scope='shell',
      restore_from=None,
      sync_period=None,
      use_gpu=False,
      verbose=True,
      **kwargs):
    self.config = ConfigDict(kwargs)
    self.verbose = verbose
    self._obs_spec = obs_spec
    if sync_period is not None:
      self._sync_checker = SyncEveryNSteps(sync_period)
      assert self._sync_checker.should_sync(0)  # must sync at the beginning
    else:
      self._sync_checker = SyncNever()
    self._step_number = 0
    self._agent_scope = agent_scope

    self._graph = tf.Graph()
    with self._graph.as_default():
      if use_gpu:
        config = tf.ConfigProto()
        config.gpu_options.allow_growth = True
        self.sess = tf.Session(config=config)
      else:
        self.sess = tf.Session()

      self._agent = agent_class(name=agent_scope,
                                action_spec=action_spec,
                                seed=seed,
                                **agent_config)

      self._batch_size_ph = tf.placeholder_with_default(batch_size,
                                                        shape=(),
                                                        name='shell_batch_size_ph')
      self._initial_state_op = self._agent.initial_state(self._batch_size_ph)
      # initialize weights randomly.
      dummy_initial_state = self.sess.run(self._initial_state_op)

      self._mk_phs(dummy_initial_state)
      self._step_output = self._agent.step(self._step_type_ph, self._reward_ph,
                                           copy.copy(self._obs_ph), self._next_state_ph)

      # initialize weights randomly.
      self.sess.run(tf.global_variables_initializer())
      self.sess.run(tf.local_variables_initializer())
      self._variables = tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, scope=agent_scope)
      self._variable_names = [var.name for var in self._variables]

      # assert that all trainable variables are subset of self._variables
      for var in tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope=agent_scope):
        assert var.name in self._variable_names

      logging.info('Number of Variables identified for syncing: %d', len(self._variables))
      logging.info('Variable names for syncing: %s', ', '.join(self._variable_names))
      self._var_name_to_phs = dict()
      self._var_names_to_assign_ops = dict()
      for var in self._variables:
        ph = tf.placeholder(dtype=var.dtype,
                            shape=var.shape,
                            name='assign_%s_ph' % var.name.replace(':', '_'))
        self._var_name_to_phs[var.name] = ph
        self._var_names_to_assign_ops[var.name] = tf.assign(var, ph, use_locking=True)
      if restore_from:
        self.restore_from_checkpoint(restore_from)
    self._next_state = None
    self._ps_client = None

  @property
  def next_state(self):
    if self._next_state is None:
      self._next_state = self.sess.run(self._initial_state_op)

    return self._next_state

  def _mk_phs(self, initial_state_dummy_spec):

    def mk_ph(spec):
      return tf.placeholder(dtype=spec.dtype, shape=spec.shape, name='shell_' + spec.name + '_ph')

    self._step_type_ph = tf.placeholder(dtype=tf.int8, shape=(None, ), name='shell_step_type_ph')
    self._reward_ph = tf.placeholder(dtype=tf.float32, shape=(None, ), name='shell_reward_ph')
    self._obs_ph = nest.map_structure(mk_ph, self._obs_spec)
    self._next_state_ph = tf.placeholder(dtype=initial_state_dummy_spec.dtype,
                                         shape=initial_state_dummy_spec.shape,
                                         name='next_state_ph')

  def _setup_ps_client(self):
    """Initialize self._ps_client and connect it to the ps."""
    self._ps_client = ParameterClient(host=os.environ['SYMPH_PS_SERVING_HOST'],
                                      port=os.environ['SYMPH_PS_SERVING_PORT'],
                                      agent_scope=self._agent_scope,
                                      timeout=self.config.ps_client_timeout,
                                      not_ready_sleep=self.config.ps_client_not_ready_sleep)

  def _pull_vars(self):
    """get weights from the parameter server."""
    params, unused_info = self._ps_client.fetch_parameter_with_info(self._variable_names)
    return params

  def _sync_variables(self):
    var_vals = self._pull_vars()
    if var_vals:
      assert sorted(var_vals.keys()) == sorted(self._variable_names) == sorted(
          self._var_names_to_assign_ops.keys())
      for var_name, assign_op in self._var_names_to_assign_ops.items():
        self.sess.run(assign_op, feed_dict={self._var_name_to_phs[var_name]: var_vals[var_name]})
      logging.info("Synced weights.")

  def sync(self):
    if self._ps_client is None:
      self._setup_ps_client()
    return self._sync_variables()

  def restore_from_checkpoint(self, restore_path):
    l = tf.train.list_variables(restore_path)
    restore_map = {}
    # strip ":%d" out from variable names.
    var_names = list(map(lambda k: k.split(':')[0], self._variable_names))
    var_names_left = set(var_names)
    unrestored = []
    for v, _ in l:
      # edit the scope.
      v2 = f'{self._agent_scope}/{"/".join(v.split("/")[1:])}'
      if v2 in var_names:
        restore_map[v] = self._variables[var_names.index(v2)]
        var_names_left.remove(v2)
      else:
        # not required for shell.
        if 'adam' in v.lower() or 'value_torso' in v.lower() or 'optimize' in v.lower(
        ) or 'global_step' in v.lower():
          pass
        else:
          unrestored.append(v)

    if len(restore_map) == 0:
      print(f'WARNING: No variables found to restore in checkpoint {restore_map}!')

    if var_names_left:
      raise Exception(f'Not all required variables restored: {var_names_left}')

    if unrestored:
      print(unrestored)
      raise Exception(
          f'Restoring only {len(restore_map)} variables from {len(l)} found in the checkpoint {restore_path}!'
      )
    saver = tf.train.Saver(var_list=restore_map)
    saver.restore(self.sess, restore_path)
    print(f'***********************************************')
    print(f'Checkpt restored from {restore_path}')
    print(f'***********************************************')

  def step(self, step_type, reward, observation):
    if self._sync_checker.should_sync(self._step_number):
      self.sync()

    # bass the batch through pre-processing
    step_type, reward, obs, next_state = self._agent.step_preprocess(step_type, reward,
                                                                     observation, self.next_state)
    nest.assert_same_structure(self._obs_ph, observation)
    obs_feed_dict = {
        obs_ph: obs_val
        for obs_ph, obs_val in zip(nest.flatten(self._obs_ph), nest.flatten(observation))
    }

    step_output = self.sess.run(self._step_output,
                                feed_dict={
                                    self._step_type_ph: step_type,
                                    self._reward_ph: reward,
                                    self._next_state_ph: next_state,
                                    **obs_feed_dict,
                                })
    if self.verbose and self._step_number % 100 == 0:
      print(step_output)
    self._next_state = step_output.next_state
    self._step_number += 1
    return step_output

  def step_output_spec(self):

    def mk_spec(tensor):
      return ArraySpec(dtype=tensor.dtype.as_numpy_dtype, shape=tensor.shape, name=tensor.name)

    return dict(nest.map_structure(mk_spec, self._step_output)._asdict())
