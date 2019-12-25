"""Actor cls. Responsible for batched policy evaluation.
  Syncs the policy weights with PS and pushes the
  experience out to exp_sender.

  Env variables used:
    SYMPH_COLLECTOR_FRONTEND_HOST
    SYMPH_COLLECTOR_FRONTEND_PORT
    SYMPH_SPEC_PORT
"""

from __future__ import absolute_import, division, print_function

import logging
import os

from liaison.env.batch import ParallelBatchedEnv, SerialBatchedEnv

from .actor import Actor as BaseActor
from .exp_sender import ExpSender
from .full_episode_trajectory import Trajectory as FullEpisodeTrajectory
from .spec_server import SpecServer
from .trajectory import Trajectory


class Actor(BaseActor):
  """
  Actor is responsible for the following.

  (1) Create a shell and batched environments.
  (2) Pushes experience out to exp_sender.

  """

  def __init__(
      self,
      actor_id,
      shell_class,
      shell_config,
      env_class,
      env_configs,
      traj_length,
      seed,
      batch_size=1,  # num_envs
      n_unrolls=None,  # None => loop forever
      use_parallel_envs=False,
      use_threaded_envs=False,
      discount_factor=None,
      **sess_config):

    del sess_config
    assert isinstance(actor_id, int)
    self.batch_size = batch_size
    self._traj_length = traj_length
    if use_parallel_envs:
      self._env = ParallelBatchedEnv(batch_size,
                                     env_class,
                                     env_configs,
                                     seed,
                                     use_threads=use_threaded_envs)
    else:
      self._env = SerialBatchedEnv(batch_size, env_class, env_configs, seed)
    self._action_spec = self._env.action_spec()
    self._obs_spec = self._env.observation_spec()
    self._shell = shell_class(
        action_spec=self._action_spec,
        obs_spec=self._obs_spec,
        seed=seed,
        batch_size=batch_size,
        **shell_config,
    )

    self._traj = FullEpisodeTrajectory(
        obs_spec=self._obs_spec,
        step_output_spec=self._shell.step_output_spec(),
        batch_size=batch_size,
        discount_factor=discount_factor,
        traj_length=traj_length)

    if actor_id == 0:
      self._start_spec_server()

    self._setup_exp_sender()
    # blocking call -- runs forever
    self.run_loop(n_unrolls)

  def run_loop(self, n_unrolls):
    ts = self._env.reset()
    self._traj.reset()
    self._traj.start(next_state=self._shell.next_state, **dict(ts._asdict()))
    i = 0
    while True:
      if n_unrolls is not None:
        if i == n_unrolls:
          return
      step_output = self._shell.step(step_type=ts.step_type,
                                     reward=ts.reward,
                                     observation=ts.observation)
      ts = self._env.step(step_output.action)
      self._traj.add(step_output=step_output, **dict(ts._asdict()))
      if i > 0 and i % self._traj_length == 0:
        # dont reset the trajectory.
        exps = self._traj.debatch_and_stack()
        self._send_experiences(exps)
      i += 1
