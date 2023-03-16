from mlflow.protos.service_pb2 import (
    CreateExperiment,
    MlflowService,
)
from mlflow.protos import databricks_pb2

# def get_endpoints():
#     """
#     :return: List of tuples (path, handler, methods)
#     """

#     def get_service_endpoints(service):
#         ret = []
#         for service_method in service.DESCRIPTOR.methods:
#             endpoints = service_method.GetOptions().Extensions[databricks_pb2.rpc].endpoints
#             for endpoint in endpoints:
#                 for http_path in _get_paths(endpoint.path):
#                     handler = get_handler(service().GetRequestClass(service_method))
#                     ret.append((http_path, handler, [endpoint.method]))
#         return ret

#     return (
#         get_service_endpoints(MlflowService)

d = {}
for service_method in MlflowService.DESCRIPTOR.methods:
    endpoints = service_method.GetOptions().Extensions[databricks_pb2.rpc].endpoints
    for endpoint in endpoints:
        d[MlflowService().GetRequestClass(service_method)] = endpoint.path

print(d)
