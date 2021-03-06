from liaison.utils import ConfigDict


def get_config():
  config = ConfigDict()

  config.learner = ConfigDict()
  config.learner.publish_every = 100
  config.learner.checkpoint_every = int(1e9)
  config.learner.n_train_steps = int(1e9)
  config.learner.use_gpu = True
  config.learner.batch_size = 8
  # max number of samples (not batches) that could be waiting in the prefetch queue
  config.learner.max_prefetch_queue = 16
  # prefetch workers are spawned in a seperate process.
  config.learner.prefetch_processes = 1
  config.learner.prefetch_threads_per_process = 8
  config.learner.inmem_tmp_dir = '/tmp/caraml/'
  # first sess.run is not profiled.
  # generates a profile after every this many steps.
  config.learner.profile_step = 5
  config.learner.restore_from = ''
  config.learner.compress_before_send = True

  config.actor = ConfigDict()
  config.actor.class_path = 'liaison.distributed.actor'
  config.actor.class_name = 'Actor'
  config.actor.n_unrolls = None  # loop forever.
  config.actor.use_parallel_envs = True
  config.actor.use_threaded_envs = False
  config.actor.discount_factor = 1.0
  config.actor.compress_before_send = True

  config.bundled_actor = ConfigDict()
  config.bundled_actor.n_actors = 64

  config.shell = ConfigDict()
  # shell class path is default to the distributed folder.
  config.shell.class_path = 'liaison.distributed.shell'
  config.shell.class_name = 'Shell'
  config.shell.agent_scope = 'shell'
  config.shell.ps_client_timeout = 2
  config.shell.ps_client_not_ready_sleep = 2
  config.shell.sync_period = 10  # in # steps.
  config.shell.use_gpu = True
  config.shell.restore_from = None

  config.replay = ConfigDict()
  config.replay.class_path = 'liaison.replay.uniform_replay'
  config.replay.class_name = 'Replay'
  config.replay.load_balanced = False  # unknown bug
  config.replay.n_shards = 1
  config.replay.evict_interval = 0
  config.replay.memory_size = 100
  config.replay.sampling_start_size = 0
  config.replay.tensorboard_display = True
  config.replay.loggerplex = ConfigDict()
  config.replay.loggerplex.tensorboard_display = True
  config.replay.loggerplex.enable_local_logger = True
  config.replay.loggerplex.local_logger_level = 'info'
  config.replay.loggerplex.local_logger_time_format = 'hms'
  config.replay.compress_before_send = True
  config.replay.max_times_sampled = 5

  config.loggerplex = ConfigDict()
  config.loggerplex.enable_local_logger = True
  config.loggerplex.time_format = 'hms'
  config.loggerplex.local_logger_level = 'info'
  config.loggerplex.local_logger_time_format = 'hms'
  config.loggerplex.overwrite = True
  config.loggerplex.level = 'info'
  config.loggerplex.show_level = True

  config.tensorplex = ConfigDict()
  config.tensorplex.tensorboard_preferred_ports = [6006 + i for i in range(100)]
  config.tensorplex.systemboard_preferred_ports = [7007 + i for i in range(100)]
  config.tensorplex.max_processes = 1
  config.tensorplex.agent_bin_size = 64
  config.tensorplex.serializer = 'pickle'
  config.tensorplex.deserializer = 'pickle'

  config.ps = ConfigDict()
  # config.ps.n_shards = 1

  config.irs = ConfigDict()
  config.irs.n_shards = 1
  config.irs.max_to_keep = 20
  config.irs.keep_ckpt_every_n_hrs = 1

  return config
