import argparse
import functools
import os
import pickle
from multiprocessing.pool import ThreadPool

import numpy as np
from liaison.daper.milp.dataset import MILP
from liaison.daper.milp.generate_graph import generate_instance
from pyscipopt import (SCIP_HEURTIMING, SCIP_PARAMSETTING, SCIP_RESULT, Heur,
                       Model)

parser = argparse.ArgumentParser()
parser.add_argument('--out_file', type=str, required=True)
parser.add_argument('--problem_type', type=str, required=True)
parser.add_argument('--problem_size', type=int, required=True)
parser.add_argument('--time_limit', type=int, default=None)
parser.add_argument('--seed', type=int, required=True)
parser.add_argument('--score_threshold', type=float, default=-1e20)
parser.add_argument('--gap', type=float, default=0.)
parser.add_argument('--n_threads', type=int, default=1)
parser.add_argument('--only_collect_metadata',
                    action='store_true',
                    help='Only collects stats instead of writing the problem.')
args = parser.parse_args()


class LogBestSol(Heur):

  def __init__(self):
    super(LogBestSol, self).__init__()
    self.primal_integral = 0.
    self.i = 0
    # list of tuples of (primal gap switch step, primal gap)
    self.l = []

  def heurexec(self, heurtiming, nodeinfeasible):
    sol = self.model.getBestSol()
    obj = self.model.getSolObjVal(sol)
    self.primal_integral += obj
    if self.l:
      if self.l[-1][1] != obj:
        self.l.append((self.i, obj))
    else:
      self.l.append((self.i, obj))
    self.i += 1
    return dict(result=SCIP_RESULT.DELAYED)


def sample_milp_work(rng):
  milp = MILP()
  milp.problem_type = args.problem_type
  mip = generate_instance(args.problem_type, args.problem_size, rng)
  if not args.only_collect_metadata:
    milp.mip = mip
  else:
    milp.mip = None

  model = Model()
  model.hideOutput()
  heur = LogBestSol()
  model.includeHeur(heur,
                    "PyHeur",
                    "custom heuristic implemented in python",
                    "Y",
                    timingmask=SCIP_HEURTIMING.BEFORENODE)

  mip.add_to_scip_solver(model)
  model.setRealParam('limits/gap', args.gap)
  model.optimize()
  milp.optimal_objective = model.getObjVal()
  if not args.only_collect_metadata:
    milp.optimal_solution = {
        var.name: model.getVal(var)
        for var in model.getVars()
    }
  milp.is_optimal = (model.getStatus() == 'optimal')
  milp.optimal_sol_metadata.n_nodes = model.getNNodes()
  milp.optimal_sol_metadata.gap = model.getGap()
  milp.optimal_sol_metadata.primal_integral = heur.primal_integral
  milp.optimal_sol_metadata.primal_gaps = heur.l

  feasible_sol = model.getSols()[-1]
  milp.feasible_objective = model.getSolObjVal(feasible_sol)
  if not args.only_collect_metadata:
    milp.feasible_solution = {
        var.name: feasible_sol[var]
        for var in model.getVars()
    }
  return milp


def main():
  optimal_milp = None
  best_score = -np.inf

  N = args.n_threads
  rngs = [np.random.RandomState(args.seed + i) for i in range(N)]

  while best_score < args.score_threshold:
    # take care of random state if the following threadpool is replaced with processpool
    with ThreadPool(N) as pool:
      milps = pool.map(sample_milp_work, rngs)

    for milp in milps:
      score = milp.optimal_sol_metadata.primal_integral
      if best_score < score:
        best_score = score
        optimal_milp = milp

  os.makedirs(os.path.dirname(args.out_file), exist_ok=True)
  with open(args.out_file, 'wb') as f:
    pickle.dump(optimal_milp, f)


if __name__ == '__main__':
  main()
