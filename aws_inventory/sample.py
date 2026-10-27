"""Synthetic control-plane fixtures. No credentials, sockets, or AWS clients are used."""
from datetime import timedelta

from .config import SAMPLE_ACCOUNT

REGION = "ap-northeast-2"
INSTANCE_A = "i-00000000000000001"
INSTANCE_B = "i-00000000000000002"
CLUSTER = f"arn:aws:ecs:{REGION}:{SAMPLE_ACCOUNT}:cluster/sample"
SERVICE = f"arn:aws:ecs:{REGION}:{SAMPLE_ACCOUNT}:service/sample/api"


class SampleSession:
    def client(self, name, *, region_name, config=None):
        if region_name != ("us-east-1" if name == "sts" else REGION):
            raise ValueError("Sample client Region mismatch.")
        return SampleClient(name)


class SampleClient:
    def __init__(self, service=None):
        self.service = service

    def __getattr__(self, operation):
        if operation.startswith("_"):
            raise AttributeError(operation)

        def call(**params):
            from .config_samples import response as configuration_response
            from .network_samples import response as network_response
            for adapter in (network_response, configuration_response):
                try:
                    return adapter(self.service, operation, params)
                except KeyError:
                    continue
            raise AttributeError(f"Unregistered sample operation: {self.service}.{operation}")
        return call

    def get_caller_identity(self):
        return {"Account": SAMPLE_ACCOUNT, "Arn": f"arn:aws:iam::{SAMPLE_ACCOUNT}:role/sample"}

    def describe_instances(self, **kwargs):
        return {"Reservations": [{"Instances": [
            {"InstanceId": INSTANCE_A, "State": {"Name": "running"}, "InstanceType": "t3.small",
             "Placement": {"AvailabilityZone": "ap-northeast-2a"},
             "VpcId": "vpc-00000000000000001", "SubnetId": "subnet-00000000000000001"},
            {"InstanceId": INSTANCE_B, "State": {"Name": "running"}, "InstanceType": "t3.medium",
             "Placement": {"AvailabilityZone": "ap-northeast-2c"}},
        ]}]}

    def describe_instance_status(self, **kwargs):
        return {"InstanceStatuses": [
            {"InstanceId": resource, "InstanceState": {"Name": "running"},
             "InstanceStatus": {"Status": "impaired" if resource == INSTANCE_B else "ok"},
             "SystemStatus": {"Status": "ok"}}
            for resource in kwargs["InstanceIds"] if resource in {INSTANCE_A, INSTANCE_B}
        ]}

    def describe_db_instances(self, **kwargs):
        return {"DBInstances": [
            {"DBInstanceIdentifier": "sample-orders", "DBInstanceStatus": "available", "Engine": "postgres",
             "EngineVersion": "16", "DBInstanceClass": "db.t4g.medium", "MultiAZ": True,
             "StorageEncrypted": True, "PubliclyAccessible": False,
             "DBSubnetGroup": {"VpcId": "vpc-00000000000000001"},
             "DBInstanceArn": f"arn:aws:rds:{REGION}:{SAMPLE_ACCOUNT}:db:sample-orders"}
        ]}

    def list_clusters(self, **kwargs):
        return {"clusterArns": [CLUSTER]}

    def list_services(self, **kwargs):
        return {"serviceArns": [SERVICE] if kwargs["cluster"] == "sample" else []}

    def describe_services(self, **kwargs):
        services = []
        if kwargs["cluster"] == "sample" and "api" in kwargs["services"]:
            services.append({
                "serviceArn": SERVICE, "serviceName": "api", "clusterArn": CLUSTER,
                "status": "ACTIVE", "desiredCount": 2, "runningCount": 1, "pendingCount": 1,
                "deployments": [{"id": "sample-deployment", "status": "PRIMARY", "rolloutState": "IN_PROGRESS",
                                 "desiredCount": 2, "runningCount": 1, "pendingCount": 1}],
            })
        return {"services": services, "failures": []}

    def list_functions(self, **kwargs):
        return {"Functions": [
            {"FunctionName": "sample-worker", "FunctionArn": f"arn:aws:lambda:{REGION}:{SAMPLE_ACCOUNT}:function:sample-worker",
             "Runtime": "python3.12", "MemorySize": 256, "Timeout": 30},
            {"FunctionName": "sample-idle", "FunctionArn": f"arn:aws:lambda:{REGION}:{SAMPLE_ACCOUNT}:function:sample-idle",
             "Runtime": "python3.12", "MemorySize": 128, "Timeout": 10},
        ]}

    def get_function_configuration(self, **kwargs):
        return {"FunctionName": kwargs["FunctionName"], "State": "Active", "LastUpdateStatus": "Successful"}

    def get_metric_data(self, **kwargs):
        rows = []
        for query in kwargs["MetricDataQueries"]:
            metric = query["MetricStat"]["Metric"]
            missing = any(d["Value"] == "sample-idle" for d in metric["Dimensions"])
            value = {"Invocations": 120.0, "Errors": 3.0, "Throttles": 1.0, "Duration": 87.0}.get(metric["MetricName"], 12.0)
            rows.append({
                "Id": query["Id"], "StatusCode": "Complete",
                "Values": [] if missing else [value],
                "Timestamps": [] if missing else [kwargs["EndTime"] - timedelta(minutes=5)],
            })
        return {"MetricDataResults": rows}

    def describe_alarms(self, **kwargs):
        if kwargs.get("StateValue") not in {None, "ALARM"}:
            return {"MetricAlarms": [], "CompositeAlarms": []}
        return {"MetricAlarms": [{
            "AlarmName": "sample-worker-errors", "AlarmArn": f"arn:aws:cloudwatch:{REGION}:{SAMPLE_ACCOUNT}:alarm:sample-worker-errors",
            "StateValue": "ALARM", "Namespace": "AWS/Lambda", "MetricName": "Errors",
            "Threshold": 1.0, "ComparisonOperator": "GreaterThanOrEqualToThreshold", "EvaluationPeriods": 1,
            "TreatMissingData": "missing",
        }], "CompositeAlarms": []}
