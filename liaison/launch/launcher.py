"""
Defines the LaunchSettings class that holds all the
information one needs to launch a component of surreal
"""
import os
import subprocess
import sys
from argparse import ArgumentParser
from threading import Thread

import faulthandler
import liaison.utils as U
from liaison.distributed import Actor, Learner, ShardedParameterServer
from liaison.loggers import (ConsoleLogger, DownSampleLogger, TensorplexLogger)
from liaison.irs import IRSServer
from liaison.replay import ReplayLoadBalancer
from tensorplex import Loggerplex, Tensorplex

faulthandler.enable()


class Launcher:
  """
        Launchers are shared entrypoint for surreal experiments.
        Launchers define a main function that takes commandline
        arguments in the following way.
        `python launch_ppo.py <component_name> -- [additional_args]`
        component_name defines which part of the experiment should be
        run in this process
        [additional_args] should be shared among all involved processes
        to define behavior globally
    """

  def main(self):
    """
        The main function to be called
        ```
        if __name__ == '__main__':
            launcher = Launcher()
            launcher.main()
        ```
        """
    argv = sys.argv[1:]
    parser_args = argv
    config_args = []
    if '--' in argv:
      index = argv.index('--')
      parser_args = argv[:index]
      config_args = argv[index + 1:]
    parser = ArgumentParser(description='launch a surreal component')
    parser.add_argument('component_name',
                        type=str,
                        help='which component to launch')
    args, _ = parser.parse_known_args(parser_args)

    self.config_args = config_args

    self.setup(config_args)
    self.launch(args.component_name)

  def launch(self, component_name_in):
    """
            Launches a surreal experiment

        Args:
            component_name: Allowed components:
                                agent-{*},
                                agents-{*},
                                eval-{*},
                                evals-{*},
                                replay,
                                learner,
                                ps,
                                tensorboard,
        """
    if '-' in component_name_in:
      component_name, component_id = component_name_in.split('-')
      component_id = int(component_id)
    else:
      component_name = component_name_in
      component_id = None

    if component_name == 'actor':
      self.run_actor(actor_id=component_id)
    elif component_name == 'learner':
      self.run_learner()
    elif component_name == 'ps':
      self.run_ps()
    elif component_name == 'replay':
      self.run_replay()
    elif component_name == 'replay_loadbalancer':
      self.run_replay_loadbalancer()
    elif component_name == 'replay_worker':
      self.run_replay_worker(replay_id=component_id)
    elif component_name == 'tensorboard':
      self.run_tensorboard()
    elif component_name == 'systemboard':
      self.run_systemboard()
    elif component_name == 'tensorplex':
      self.run_tensorplex()
    elif component_name == 'loggerplex':
      self.run_loggerplex()
    elif component_name == 'irs':
      self.run_irs()
    else:
      raise ValueError('Unexpected component {}'.format(component_name))

  def run_component(self, component_name):
    return subprocess.Popen(
        [sys.executable, '-u', sys.argv[0], component_name, '--'] +
        self.config_args)

  def run_actor(self, actor_id):
    """
        Launches an actor process with actor_id

    Args:
        actor_id (int): actor's id
    """

    agent_config, env_config, sess_config = (self.agent_config,
                                             self.env_config, self.sess_config)
    agent_class = U.import_obj(agent_config.class_name,
                               agent_config.class_path)

    shell_class = U.import_obj(sess_config.shell.class_name,
                               sess_config.shell.class_path)

    env_class = U.import_obj(env_config.class_name, env_config.class_path)

    shell_config = dict(agent_class=agent_class,
                        agent_config=self.agent_config,
                        **self.sess_config.shell)

    actor_config = dict(actor_id=actor_id,
                        shell_class=shell_class,
                        shell_config=shell_config,
                        env_class=env_class,
                        env_configs=[self.env_config] * self.batch_size,
                        traj_length=self.traj_length,
                        seed=self.seed,
                        batch_size=self.batch_size,
                        **self.sess_config.actor)

    Actor(**actor_config)  # blocking constructor.

  def _setup_learner_loggers(self):
    loggers = []
    loggers.append(ConsoleLogger())
    loggers.append(TensorplexLogger(client_id='learner/learner'))
    return loggers

  def _setup_learner_system_loggers(self):
    loggers = []
    loggers.append(ConsoleLogger(name='system'))
    loggers.append(
        TensorplexLogger(client_id='learner/learner',
                         host=os.environ['SYMPH_TENSORPLEX_SYSTEM_HOST'],
                         port=os.environ['SYMPH_TENSORPLEX_SYSTEM_PORT']))
    return loggers

  def run_learner(self, iterations=None):
    """
        Launches the learner process.
        Learner consumes experience from replay
        and publishes experience to parameter server
    """

    agent_class = U.import_obj(self.agent_config.class_name,
                               self.agent_config.class_path)
    learner = Learner(agent_class=agent_class,
                      agent_config=self.agent_config,
                      batch_size=self.batch_size,
                      traj_length=self.traj_length,
                      seed=self.seed,
                      loggers=self._setup_learner_loggers(),
                      system_loggers=self._setup_learner_system_loggers(),
                      **self.sess_config.learner)
    learner.main()

  def run_ps(self):
    """
        Lauches the parameter server process.
        Serves parameters to agents
    """
    server = ShardedParameterServer(shards=self.sess_config.ps.n_shards)

    server.launch()
    server.join()

  def run_replay(self):
    """
        Launches the replay process.
        Replay collects experience from agents
        and serve them to learner
    """
    loadbalancer = self.run_component('replay_loadbalancer')
    components = [loadbalancer]
    for replay_id in range(self.sess_config.replay.n_shards):
      component_name = 'replay_worker-{}'.format(replay_id)
      replay = self.run_component(component_name)
      components.append(replay)
    U.wait_for_popen(components)

  def run_replay_loadbalancer(self):
    """
            Launches the learner and agent facing load balancing proxys
            for replays
        """
    loadbalancer = ReplayLoadBalancer()
    loadbalancer.launch()
    loadbalancer.join()

  def run_replay_worker(self, replay_id):
    """
            Launches a single replay server

        Args:
            replay_id: The id of the replay server
        """

    replay_class = U.import_obj(self.sess_config.replay.class_name,
                                self.sess_config.replay.class_path)

    replay = replay_class(seed=self.seed,
                          index=replay_id,
                          **self.sess_config.replay)
    replay.start_threads()
    replay.join()

  def _launch_tensorboard(self, folder, port):

    cmd = ['tensorboard', '--logdir', folder, '--port', str(port)]
    subprocess.call(cmd)

  def run_tensorboard(self):
    """
        Launches a tensorboard process
    """
    # Visualize all work units with tensorboard.
    folder = os.path.join(self.results_folder, 'tensorplex_metrics')
    self._launch_tensorboard(folder, os.environ['SYMPH_TENSORBOARD_PORT'])

  def run_systemboard(self):
    folder = os.path.join(self.results_folder, 'tensorplex_system_profiles')
    self._launch_tensorboard(folder, os.environ['SYMPH_SYSTEMBOARD_PORT'])

  def run_tensorplex(self):
    """
            Launches a tensorplex process.
            It receives data from multiple sources and
            send them to tensorboard.
        """
    folder1 = os.path.join(self.results_folder, 'tensorplex_metrics',
                           str(self.work_id))
    folder2 = os.path.join(self.results_folder, 'tensorplex_system_profiles',
                           str(self.work_id))
    tensorplex_config = self.sess_config.tensorplex
    threads = []

    for folder, port in zip([folder1, folder2], [
        os.environ['SYMPH_TENSORPLEX_PORT'],
        os.environ['SYMPH_TENSORPLEX_SYSTEM_PORT']
    ]):
      tensorplex = Tensorplex(
          folder,
          max_processes=tensorplex_config.max_processes,
      )
      """
        Tensorboard categories:
          learner/replay/eval: algorithmic level, e.g. reward, ...
          ***-core: low level metrics, i/o speed, computation time, etc.
          ***-system: Metrics derived from raw metric data in core,
                      i.e. exp_in/exp_out
      """
      tensorplex.register_normal_group('learner').register_indexed_group(
          'actor', tensorplex_config.agent_bin_size).register_indexed_group(
              'replay', 100).register_indexed_group('ps', 100)

      thread = Thread(target=tensorplex.start_server, kwargs=dict(port=port))
      thread.start()
      threads.append(thread)

    for thread in threads:
      thread.join()

  def run_loggerplex(self):
    """
            Launches a loggerplex server.
            It helps distributed logging.
        """
    folder = os.path.join(self.results_folder, 'loggerplex', str(self.work_id))
    loggerplex_config = self.sess_config.loggerplex

    loggerplex = Loggerplex(os.path.join(folder, 'logs'),
                            level=loggerplex_config.level,
                            overwrite=loggerplex_config.overwrite,
                            show_level=loggerplex_config.show_level,
                            time_format=loggerplex_config.time_format)
    port = os.environ['SYMPH_LOGGERPLEX_PORT']
    loggerplex.start_server(port)

  def run_irs(self):
    self._irs_server = IRSServer(
        results_folder=self.results_folder,
        agent_config=self.agent_config,
        env_config=self.env_config,
        sess_config=self.sess_config,
        network_config=self.network_config,
        exp_name=self.experiment_name,
        exp_id=self.experiment_id,
        work_id=self.work_id,
        configs_folder=os.path.join(self.results_folder, 'config',
                                    str(self.work_id)),
        src_folder=os.path.join(self.results_folder, 'src', str(self.work_id)),
        checkpoint_folder=os.path.join(self.results_folder, 'checkpoints',
                                       str(self.work_id)),
        cmd_folder=os.path.join(self.results_folder, 'cmds',
                                str(self.work_id)),
        **self.sess_config.irs)
    self._irs_server.launch()
    self._irs_server.join()
