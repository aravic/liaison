export KMP_AFFINITY=none
N=32
N_LOCAL_MOVES=20
MAX_NODES=50
HEURISTICS="random rins"

case $1 in

  cauction)
    NAME=cauction_100
    DATASET=milp-cauction-100-filtered
    K=5
    RESTORE_FROM=/home/gridsan/addanki/results/1481/100-dataset-no-ar/checkpoints/1/250000/learner-250000
    EXTRA_ARGS="--heur_frequency=-1"
    ;;

  facilities)
    NAME=facilities_100
    DATASET=milp-facilities-100
    K=5
    RESTORE_FROM=/home/gridsan/addanki/results/1486/milp-facilities-100/checkpoints/0/36000/learner-36000
    EXTRA_ARGS="--heur_frequency=-1 --agent_config.model.edge_embed_dim=16 --agent_config.model.node_embed_dim=16 --agent_config.model.global_embed_dim=8"
    ;;

  corlat)
    NAME=corlat
    DATASET=milp-corlat
    K=25
    RESTORE_FROM=/home/gridsan/addanki/results/1484/corlat-dataset-k-25/checkpoints/0/184000/learner-184000
    EXTRA_ARGS="--heur_frequency=10000"
    ;;

  indset)
    NAME=indset
    DATASET=milp-indset-100-filtered
    K=10
    RESTORE_FROM='/home/gridsan/addanki/results/1488/indset/checkpoints/0/204000/learner-204000'
    EXTRA_ARGS="--heur_frequency=-1 --agent_config.model.edge_embed_dim=16 --agent_config.model.node_embed_dim=16 --agent_config.model.global_embed_dim=8"
    ;;

  setcover)
    NAME=setcover
    DATASET=milp-setcover-100-filtered
    K=10
    RESTORE_FROM='/home/gridsan/addanki/results/1487/setcover/checkpoints/1/76000/learner-76000'
    EXTRA_ARGS="--heur_frequency=-1 --agent_config.model.edge_embed_dim=16 --agent_config.model.node_embed_dim=16 --agent_config.model.global_embed_dim=8"
    ;;

  *)
    echo 'Unknown argument provided'
    exit 1
    ;;
esac

for i in `seq 0 $((N-1))`; do
  python liaison/scip/run_graph.py -- \
  -n $NAME \
  --max_nodes=${MAX_NODES} \
  --use_parallel_envs \
  --n_local_moves=${N_LOCAL_MOVES} \
  --batch_size=8 \
  --agent_config_file=liaison/configs/agent/gcn_rins.py \
  --sess_config_file=liaison/configs/session_config.py \
  --env_config_file=liaison/configs/env/rins.py \
  --agent_config.model.class_path='liaison.agents.models.bipartite_gcn_rins' \
  --sess_config.shell.restore_from=${RESTORE_FROM} \
  \
  --env_config.class_path=liaison.env.rins_v2 \
  --env_config.make_obs_for_bipartite_graphnet=True \
  --env_config.muldi_actions=False \
  --env_config.dataset=${DATASET} \
  --env_config.dataset_type=test \
  --env_config.n_graphs=1 \
  --env_config.k=$K \
  --gpu_ids=`expr $i % 2` \
  --env_config.graph_start_idx=$i \
  ${EXTRA_ARGS} &
done

wait
sudo killall run_graph.py

for i in `seq 0 $((N-1))`; do
  # without agent.
  python liaison/scip/run_graph.py -- \
  -n $NAME \
  --max_nodes=${MAX_NODES} \
  --without_agent \
  --use_parallel_envs \
  --n_local_moves=${N_LOCAL_MOVES} \
  --batch_size=8 \
  --agent_config_file=liaison/configs/agent/gcn_rins.py \
  --sess_config_file=liaison/configs/session_config.py \
  --env_config_file=liaison/configs/env/rins.py \
  \
  --agent_config.model.class_path='liaison.agents.models.bipartite_gcn_rins' \
  --sess_config.shell.restore_from=${RESTORE_FROM} \
  \
  --env_config.class_path=liaison.env.rins_v2 \
  --env_config.make_obs_for_bipartite_graphnet=True \
  --env_config.muldi_actions=False \
  --env_config.dataset=${DATASET} \
  --env_config.dataset_type=test \
  --env_config.n_graphs=1 \
  --env_config.k=$K \
  --env_config.graph_start_idx=$i \
  ${EXTRA_ARGS} &
done

wait
sudo killall run_graph.py

for heuristic in $HEURISTICS; do
  for i in `seq 0 $((N-1))`; do
    python liaison/scip/run_graph.py -- \
      -n $NAME \
      --max_nodes=${MAX_NODES} \
      --gap=.05 \
      --heuristic=$heuristic \
      --use_parallel_envs \
      --n_local_moves=${N_LOCAL_MOVES} \
      --batch_size=8 \
      --agent_config_file=liaison/configs/agent/gcn_rins.py \
      --sess_config_file=liaison/configs/session_config.py \
      --env_config_file=liaison/configs/env/rins.py \
      \
      --agent_config.model.class_path='liaison.agents.models.bipartite_gcn_rins' \
      \
      --env_config.class_path=liaison.env.rins_v2 \
      --env_config.make_obs_for_bipartite_graphnet=True \
      --env_config.muldi_actions=False \
      --env_config.dataset=${DATASET} \
      --env_config.dataset_type=test \
      --env_config.n_graphs=1 \
      --env_config.k=$K \
      --env_config.graph_start_idx=$i \
      ${EXTRA_ARGS} &
  done
  wait
done

wait
sudo killall run_graph.py
