from liaison.configs.agent.config import get_config as get_base_config
from liaison.utils import ConfigDict


def get_config():
  config = get_base_config()

  # required fields.
  config.class_path = "liaison.agents.gcn"
  config.class_name = "Agent"

  config.model = ConfigDict()
  config.model.class_path = "liaison.agents.models.gcn_attn_rins"
  config.model.n_prop_layers = 4
  config.model.node_hidden_layer_sizes = [32]
  config.model.edge_hidden_layer_sizes = [32]
  config.model.key_dim = 32
  config.model.value_dim = 32
  config.model.num_heads = 4
  config.model.node_embed_dim = 32
  config.model.edge_embed_dim = 32
  config.query_key_product_hidden_layer_sizes = [16]

  config.clip_rho_threshold = 1.0
  config.clip_pg_rho_threshold = 1.0

  config.loss = ConfigDict()
  config.loss.vf_loss_coeff = 1.0

  return config
