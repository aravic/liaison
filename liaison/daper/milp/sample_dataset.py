"""
python liaison/daper/milp/sample_dataset.py --out_dir=/tmp/milp -- --problem_type=facilities --problem_size=3
"""
import argparse
import os
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--out_dir', type=str, required=True)
parser.add_argument('--n_training_samples', type=int, default=1000)
parser.add_argument('--n_valid_samples', type=int, default=100)
parser.add_argument('--n_test_samples', type=int, default=100)
REMAINDER = ''


def preprocess(argv):
  if '--' in sys.argv:
    global REMAINDER
    idx = sys.argv.index('--')
    REMAINDER = ' '.join(sys.argv[idx + 1:])
  else:
    idx = len(sys.argv)
  return sys.argv[1:idx]


args = parser.parse_args(preprocess(sys.argv))


def cmd_gen(seed, out_file):
  cmd = "python %s --seed=%d --out_file=%s %s" % (os.path.join(
      os.path.dirname(__file__), 'sample_graph.py'), seed, out_file, REMAINDER)
  return cmd


def main():
  seed = 0
  cmds = []
  for mode, size in zip(
      ['train', 'valid', 'test'],
      [args.n_training_samples, args.n_valid_samples, args.n_test_samples]):
    for i in range(size):
      out_file = os.path.join(args.out_dir, mode, '%d.pkl' % i)
      cmds += [cmd_gen(seed, out_file)]
      seed += 1

  for cmd in cmds:
    print(cmd)


if __name__ == '__main__':
  main()
