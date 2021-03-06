import argparse
import functools
import os
import pickle
from pathlib import Path

import numpy as np
from liaison.daper.milp.dataset import MILP
from liaison.daper.milp.generate_graph import generate_instance
from liaison.scip.evaluate import get_model
from pyscipopt import (SCIP_HEURTIMING, SCIP_PARAMSETTING, SCIP_RESULT, Heur,
                       Model)

parser = argparse.ArgumentParser()
parser.add_argument('-o', '--out_dir', type=str, required=True)
parser.add_argument('--problem_type', type=str, required=True)
parser.add_argument('--problem_size', type=int, nargs='+', required=True)
parser.add_argument('-N', '--n_samples', type=int, required=True)
parser.add_argument('--seed', type=int, required=True)
parser.add_argument('--gap', type=float, default=0.)
parser.add_argument('--max_nodes', type=int)
if __name__ == '__main__':
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

  def done(self):
    self.l.append((self.i, self.model.getSolObjVal(self.model.getBestSol())))


def sample_problem_size(seed):
  rng = np.random.RandomState(seed)
  l = args.problem_size[0]
  if len(args.problem_size) > 1:
    r = args.problem_size[1]
  else:
    r = l
  return np.random.choice(list(range(l, r + 1)))


def sample_milp_work(seed):
  milp = MILP()
  milp.problem_type = args.problem_type
  milp.seed = seed
  milp.problem_size = sample_problem_size(seed)
  mip = generate_instance(args.problem_type, milp.problem_size, np.random.RandomState(seed))
  milp.mip = None

  model = get_model(seed, args.gap, args.max_nodes)
  heur = LogBestSol()
  model.includeHeur(heur,
                    "PyHeur",
                    "custom heuristic implemented in python",
                    "Y",
                    timingmask=SCIP_HEURTIMING.BEFORENODE)
  mip.add_to_scip_solver(model)
  model.optimize()
  heur.done()
  milp.optimal_objective = model.getObjVal()
  milp.is_optimal = (model.getStatus() == 'optimal')
  milp.optimal_sol_metadata.n_nodes = model.getNNodes()
  milp.optimal_sol_metadata.gap = model.getGap()
  milp.optimal_sol_metadata.primal_integral = heur.primal_integral
  milp.optimal_sol_metadata.n_sum = heur.i
  milp.optimal_sol_metadata.primal_gaps = heur.l

  milp.feasible_objective = model.getSolObjVal(model.getSols()[-1])
  return milp


def main():
  for i in range(args.n_samples):
    seed = args.seed + i
    milp = sample_milp_work(seed)
    path = Path(args.out_dir)
    path.mkdir(parents=True, exist_ok=True)
    with open(path / f'{seed}.pkl', 'wb') as f:
      pickle.dump(milp, f)


if __name__ == '__main__':
  main()
