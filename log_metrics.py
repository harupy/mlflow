import time
import numpy as np
import mlflow
import multiprocessing as mp


def log(run_id, slope, repeat):
    sleep = 3
    with mlflow.start_run(run_id=run_id):
        for epoch in range(1, repeat + 1):
            print(epoch)
            mlflow.log_metric(key="metric1", value=slope * epoch * np.log(epoch), step=epoch)
            mlflow.log_metric(key="metric2", value=slope * (1 / epoch) * np.log(epoch), step=epoch)
            time.sleep(sleep)


client = mlflow.tracking.MlflowClient()
run_uuids = [client.create_run("0").info.run_id for _ in range(2)]
runs_param = "[" + ",".join(map(lambda s: f"%22{s}%22", run_uuids)) + "]"

print(
    "URL:",
    r"http://localhost:3000/#/metric/metric1?runs=<<< runs_param >>>&experiment=0&plot_metric_keys=[%22metric1%22]&plot_layout={%22autosize%22:true,%22xaxis%22:{},%22yaxis%22:{}}&x_axis=step&y_axis_scale=linear&line_smoothness=1&show_point=true&deselected_curves=[]&last_linear_y_axis_range=[]".replace(
        "<<< runs_param >>>", runs_param
    ),
)

args_list = [(run_uuid, idx + 1, 5 + idx * 3) for idx, run_uuid in enumerate(run_uuids)]

with mp.Pool() as pool:
    pool.starmap(log, args_list)
