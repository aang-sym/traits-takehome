
from aws_cdk import (
    App,
    CfnOutput,
    Duration,
    Environment,
    RemovalPolicy,
    Stack,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_events as events,
    aws_events_targets as targets,
    aws_glue as glue,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_s3 as s3,
    aws_sns as sns,
    aws_sns_subscriptions as subscriptions,
    aws_stepfunctions as sfn,
    aws_stepfunctions_tasks as tasks,
)
from constructs import Construct


class TraitsETLStack(Stack):
    """
    CDK Stack for Traits Insights ETL pipeline.

    Implements the S3 → Glue → Athena pipeline with Step Functions orchestration
    and a Lambda-based ingestion step that calls the SkillCorner API.
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ========================================
        # S3 Buckets
        # ========================================

        # Ingestion bucket – raw files fetched from SkillCorner API land here
        self.ingestion_bucket = s3.Bucket(
            self,
            "IngestionBucket",
            bucket_name="traits-etl-skillcorner-ingestion",
            versioned=True,
            removal_policy=RemovalPolicy.RETAIN,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        # Analytics bucket – bronze / silver / gold layout
        self.analytics_bucket = s3.Bucket(
            self,
            "AnalyticsBucket",
            bucket_name="traits-etl-analytics",
            versioned=True,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="DeleteOldAnalytics",
                    expiration=Duration.days(365),
                )
            ],
            removal_policy=RemovalPolicy.RETAIN,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        # Script bucket (Glue job scripts, UDFs, dependencies)
        self.script_bucket = s3.Bucket(
            self,
            "ScriptBucket",
            bucket_name="traits-etl-scripts",
            versioned=True,
            removal_policy=RemovalPolicy.RETAIN,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        # ========================================
        # IAM Roles
        # ========================================

        # Glue job execution role
        self.glue_role = iam.Role(
            self,
            "GlueJobRole",
            assumed_by=iam.ServicePrincipal("glue.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSGlueServiceRole"
                )
            ],
        )

        # Grant Glue read/write access to buckets
        self.ingestion_bucket.grant_read(self.glue_role)
        self.analytics_bucket.grant_read_write(self.glue_role)
        self.script_bucket.grant_read(self.glue_role)

        # Lambda execution role
        self.lambda_role = iam.Role(
            self,
            "LambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
        )

        self.ingestion_bucket.grant_read_write(self.lambda_role)

        # Step Functions execution role
        self.sfn_role = iam.Role(
            self,
            "StepFunctionsRole",
            assumed_by=iam.ServicePrincipal("states.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("CloudWatchLogsFullAccess")
            ],
        )

        # Allow Step Functions to start Glue jobs
        self.sfn_role.add_to_policy(
            iam.PolicyStatement(
                actions=["glue:StartJobRun", "glue:GetJobRun", "glue:BatchStopJobRun"],
                resources=["*"],  # Narrow to specific job ARNs in a real deployment
            )
        )

        # ========================================
        # Ingestion Lambda (SkillCorner API → S3)
        # ========================================

        self.ingestion_lambda = lambda_.Function(
            self,
            "SkillCornerIngestionLambda",
            function_name="TraitsETL-SkillCornerIngestion",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="index.handler",
            role=self.lambda_role,
            timeout=Duration.seconds(60),
            memory_size=512,
            environment={
                "INGESTION_BUCKET": self.ingestion_bucket.bucket_name,
            },
            # In a real deployment this would point to packaged Lambda code that
            # calls the SkillCorner API and writes raw files into the ingestion bucket.
            code=lambda_.Code.from_asset("lambda/skillcorner_ingestion"),
        )

        # Trigger the ingestion Lambda daily at 2am UTC
        self.daily_rule = events.Rule(
            self,
            "DailyIngestionTrigger",
            schedule=events.Schedule.cron(hour="2", minute="0"),
            targets=[targets.LambdaFunction(self.ingestion_lambda)],
        )
        # ========================================
        # Glue Data Catalog
        # ========================================

        self.glue_database = glue.CfnDatabase(
            self,
            "TraitsDatabase",
            catalog_id=self.account,
            database_input=glue.CfnDatabase.DatabaseInputProperty(
                name="traits_etl",
                description="Player metrics and tracking data from SkillCorner",
            ),
        )

        # ========================================
        # Glue Jobs
        # ========================================

        # Job 1: Bronze + Silver – raw → cleaned Parquet tables
        self.bronze_silver_job = glue.CfnJob(
            self,
            "BronzeSilverJob",
            name="TraitsETL-BronzeSilver",
            role=self.glue_role.role_arn,
            command=glue.CfnJob.JobCommandProperty(
                name="glueetl",
                python_version="3",
                script_location=f"s3://{self.script_bucket.bucket_name}/glue/bronze_silver.py",
            ),
            default_arguments={
                "--job-language": "python",
                "--enable-glue-datacatalog": "true",
                "--enable-metrics": "true",
                "--TempDir": f"s3://{self.analytics_bucket.bucket_name}/temp/",
                "--INGESTION_BUCKET": self.ingestion_bucket.bucket_name,
                "--ANALYTICS_BUCKET": self.analytics_bucket.bucket_name,
            },
            glue_version="4.0",
            worker_type="G.2X",
            number_of_workers=10,
            timeout=30,
            max_retries=1,
        )

        # Job 2: Gold – compute player-level metrics
        self.gold_metrics_job = glue.CfnJob(
            self,
            "GoldMetricsJob",
            name="TraitsETL-GoldMetrics",
            role=self.glue_role.role_arn,
            command=glue.CfnJob.JobCommandProperty(
                name="glueetl",
                python_version="3",
                script_location=f"s3://{self.script_bucket.bucket_name}/glue/gold_metrics.py",
            ),
            default_arguments={
                "--job-language": "python",
                "--enable-glue-datacatalog": "true",
                "--enable-metrics": "true",
                "--ANALYTICS_BUCKET": self.analytics_bucket.bucket_name,
            },
            glue_version="4.0",
            worker_type="G.2X",
            number_of_workers=10,
            timeout=30,
            max_retries=1,
        )

        # ========================================
        # Glue Crawler (for gold tables)
        # ========================================

        self.glue_crawler = glue.CfnCrawler(
            self,
            "PlayerMetricsCrawler",
            name="TraitsETL-PlayerMetricsCrawler",
            role=self.glue_role.role_arn,
            database_name=self.glue_database.ref,
            targets=glue.CfnCrawler.TargetsProperty(
                s3_targets=[
                    glue.CfnCrawler.S3TargetProperty(
                        path=f"s3://{self.analytics_bucket.bucket_name}/gold/player_metrics/"
                    ),
                    glue.CfnCrawler.S3TargetProperty(
                        path=f"s3://{self.analytics_bucket.bucket_name}/gold/player_sprints/"
                    ),
                    glue.CfnCrawler.S3TargetProperty(
                        path=f"s3://{self.analytics_bucket.bucket_name}/gold/player_runs/"
                    ),
                    glue.CfnCrawler.S3TargetProperty(
                        path=f"s3://{self.analytics_bucket.bucket_name}/gold/player_pressing/"
                    ),
                ]
            ),
            schema_change_policy=glue.CfnCrawler.SchemaChangePolicyProperty(
                update_behavior="UPDATE_IN_DATABASE",
                delete_behavior="LOG",
            ),
        )

        # ========================================
        # Step Functions State Machine
        # ========================================

        # Glue tasks
        bronze_silver_task = tasks.GlueStartJobRun(
            self,
            "BronzeSilverTask",
            glue_job_name=self.bronze_silver_job.name,
            integration_pattern=sfn.IntegrationPattern.RUN_JOB,
            result_path="$.bronze_silver_result",
        )

        gold_metrics_task = tasks.GlueStartJobRun(
            self,
            "GoldMetricsTask",
            glue_job_name=self.gold_metrics_job.name,
            integration_pattern=sfn.IntegrationPattern.RUN_JOB,
            result_path="$.gold_metrics_result",
        )

        crawler_task = tasks.GlueStartCrawler(
            self,
            "RunCrawlerTask",
            crawler_name=self.glue_crawler.name,
            result_path="$.crawler_result",
        )

        # SNS topic for notifications
        self.notifications_topic = sns.Topic(
            self,
            "NotificationsTopic",
            display_name="Traits ETL Notifications",
        )

        self.notifications_topic.add_subscription(
            subscriptions.EmailSubscription("etl-notifications@traitsinsights.com")
        )

        notify_success = tasks.SnsPublish(
            self,
            "NotifySuccess",
            topic=self.notifications_topic,
            message=sfn.TaskInput.from_text("Traits ETL pipeline completed successfully"),
            result_path="$.notification",
        )

        notify_failure = tasks.SnsPublish(
            self,
            "NotifyFailure",
            topic=self.notifications_topic,
            message=sfn.TaskInput.from_text("Traits ETL pipeline failed"),
            result_path="$.notification",
        )

        # Basic linear workflow: BronzeSilver → GoldMetrics → Crawler → Notify
        definition = bronze_silver_task.next(gold_metrics_task).next(crawler_task).next(
            notify_success
        )

        # Catch-all error path
        definition = definition.add_catch(notify_failure, result_path="$.error")

        self.state_machine = sfn.StateMachine(
            self,
            "TraitsETLStateMachine",
            state_machine_name="TraitsETLPipeline",
            definition=definition,
            role=self.sfn_role,
            timeout=Duration.hours(2),
        )

        self.state_machine.grant_start_execution(self.ingestion_lambda)

        # ========================================
        # CloudWatch Alarms
        # ========================================

        # Alarm: State machine execution failures
        self.failure_alarm = cloudwatch.Alarm(
            self,
            "StateMachineFailureAlarm",
            alarm_name="TraitsETL-PipelineFailure",
            metric=self.state_machine.metric_failed(
                period=Duration.minutes(5),
                statistic="Sum",
            ),
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        )
        self.failure_alarm.add_alarm_action(cw_actions.SnsAction(self.notifications_topic))

        # ========================================
        # Outputs
        # ========================================

        CfnOutput(self, "IngestionBucketName", value=self.ingestion_bucket.bucket_name)
        CfnOutput(self, "AnalyticsBucketName", value=self.analytics_bucket.bucket_name)
        CfnOutput(self, "ScriptBucketName", value=self.script_bucket.bucket_name)
        CfnOutput(self, "StateMachineArn", value=self.state_machine.state_machine_arn)
        CfnOutput(self, "GlueDatabaseName", value=self.glue_database.ref)
        CfnOutput(self, "NotificationsTopicArn", value=self.notifications_topic.topic_arn)


# ========================================
# CDK App Definition
# ========================================

if __name__ == "__main__":
    app = App()

    TraitsETLStack(
        app,
        "TraitsETLStack",
        env=Environment(
            account="123456789012",  # Replace with your AWS account ID
            region="us-east-1",  # Or your preferred region
        ),
        description="ETL pipeline for SkillCorner tracking data (Traits Insights)",
    )

    app.synth()