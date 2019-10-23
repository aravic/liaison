"""Script to create programs for distributed RL.
Does the following:

"""
import itertools


def get_fuzzy_match(config, name):
  for k, v in config.items():
    if name.startswith(k):
      return v
  raise Exception('No fuzzy match found for key %s' % name)


def build_program(exp, n_actors, res_req_config):
  learner = exp.new_process('learner')
  replay = exp.new_process('replay')
  ps = exp.new_process('ps')
  irs = exp.new_process('irs')
  tensorboard = exp.new_process('tensorboard')
  tensorplex = exp.new_process('tensorplex')
  actor_pg = exp.new_process_group('actor-*')
  actors = []
  for i in range(n_actors):
    actors.append(actor_pg.new_process('actor-{}'.format(i)))

  setup_network(
      actors=actors,
      learner=learner,
      replay=replay,
      ps=ps,
      tensorboard=tensorboard,
      tensorplex=tensorplex,
      irs=irs,
  )
  for proc in [learner, replay, ps, irs, tensorplex, tensorboard] + actors:
    proc.set_costs(**get_fuzzy_match(res_req_config, proc.name))


def setup_network(*,
                  actors,
                  ps,
                  replay,
                  learner,
                  tensorplex,
                  loggerplex=None,
                  tensorboard=None,
                  systemboard=None,
                  irs=None):
  """
        Sets up the communication between surreal
        components using symphony

        Args:
            actors, (list): list of symphony processes
            ps, replay, learner, tensorplex, loggerplex, tensorboard:
                symphony processes
    """
  for proc in actors:
    proc.connects('ps-frontend')
    proc.connects('collector-frontend')

  actors[0].binds('spec')

  ps.binds('ps-frontend')
  ps.binds('ps-backend')
  ps.connects('parameter-publish')

  replay.binds('collector-frontend')
  replay.binds('sampler-frontend')
  replay.binds('collector-backend')
  replay.binds('sampler-backend')

  learner.connects('spec')
  learner.connects('sampler-frontend')
  learner.binds('parameter-publish')
  learner.binds('prefetch-queue')

  tensorplex.binds('tensorplex')
  tensorplex.binds('tensorplex-system')
  # loggerplex.binds('loggerplex')

  irs.binds('irs-frontend')
  irs.binds('irs-backend')

  for proc in itertools.chain(actors, [ps, replay, learner]):
    proc.connects('tensorplex')
    proc.connects('tensorplex-system')
    proc.connects('irs-frontend')
    # proc.connects('loggerplex')

  if tensorboard:
    tensorboard.binds('tensorboard')
  if systemboard:
    systemboard.binds('systemboard')