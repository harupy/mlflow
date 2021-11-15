import time
import numpy as np
import mlflow


with mlflow.start_run() as run:
    print(
        "URL:",
        r"http://localhost:3000/#/metric/metric1?runs=[%22<<< RUN_ID >>>%22]&experiment=0&plot_metric_keys=[%22metric1%22]&plot_layout={%22autosize%22:true,%22xaxis%22:{},%22yaxis%22:{}}&x_axis=relative&y_axis_scale=linear&line_smoothness=1&show_point=true&deselected_curves=[]&last_linear_y_axis_range=[]".replace(
            "<<< RUN_ID >>>", run.info.run_id
        ),
    )
    for epoch in range(1, 10):
        print(epoch)
        mlflow.log_metric(key="metric1", value=epoch * np.log(epoch), step=epoch)
        mlflow.log_metric(key="metric2", value=(1 / epoch) * np.log(epoch), step=epoch)
        time.sleep(3)
