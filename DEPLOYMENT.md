# AWS CI/CD deployment guide

This repository is a single Flask application. The browser UI is served from
`Backend/templates/index.html`, the analysis API and image assets are served by
the same Flask process, and the seasonal datasets are read from
`Backend/Datasets/`. Product suggestion images are served from S3 using
presigned URLs. There is no separate frontend build step.

The pipeline described here uses **GitHub → CodePipeline → CodeBuild →
CodeDeploy → EC2**. CodeDeploy installs the Python dependencies and runs the
application as a Gunicorn-managed systemd service on **one Amazon Linux 2023
EC2 instance**. This is a minimal test deployment: no load balancer, Auto
Scaling group, or custom domain is required.

## 1. Prepare the repository and S3 image bucket

1. Push the deployment-ready branch to the GitHub repository. The pipeline
   builds the branch configured in its source stage; it does not deploy local,
   uncommitted changes.
2. In S3, create or select a bucket in the same AWS Region as the application.
   Keep **Block all public access** enabled.
3. Upload the product suggestion images under the exact key prefix
   `stylespectrum_img/` (for example, `stylespectrum_img/jetblack.png`). The
   `Image Path` column in `Backend/Datasets/suggestions.xlsx` is normalized to
   that prefix by the app. Since the checked-in product images are in
   `Backend/static/images/`, you can upload them with:

   ```bash
   aws s3 sync Backend/static/images/ s3://BUCKET_NAME/stylespectrum_img/ \
     --region ap-south-2
   ```

   Replace the bucket and Region as needed; do not add `--acl public-read`.
4. Note the bucket name and Region. The EC2 instance role needs permission to
   read the objects in this prefix so that the app can create valid
   presigned URLs. Do not make the bucket public and do not put AWS access keys
   in the repository.

## 2. Create the IAM roles

Create these roles in IAM. Keep the roles in the same AWS account and Region
where practical.

### EC2 instance role

1. Create a role with **AWS service → EC2** as its trusted entity and attach it
   as the EC2 instance profile when launching the instance.
2. Grant the instance permissions for the CodeDeploy revision artifact bucket
   so its CodeDeploy agent can download releases. Restrict access to the
   pipeline's artifact bucket and the relevant object prefix. For an
   unversioned artifact bucket, the required object permission is typically
   `s3:GetObject` on `arn:aws:s3:::PIPELINE_ARTIFACT_BUCKET/*`; include
   `s3:GetObjectVersion` if the bucket is versioned. If the bucket uses a
   customer-managed KMS key, also grant `kms:Decrypt` on that key and allow it
   in the key policy.
3. Add this S3 permission for the product images, replacing `BUCKET_NAME` with
   the bucket from step 1:

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": "s3:GetObject",
         "Resource": "arn:aws:s3:::BUCKET_NAME/stylespectrum_img/*"
       }
     ]
   }
   ```

   Add `s3:ListBucket` only if you later use the application's optional image
   listing function. The running application uses the instance role through
   boto3; it does not need static credentials.

### CodeDeploy service role

Create a role trusted by `codedeploy.amazonaws.com` and attach the AWS-managed
`AWSCodeDeployRole` policy for EC2/on-premises deployments. Select this role
when you create the CodeDeploy deployment group.

### CodeBuild and CodePipeline roles

When creating the CodeBuild project and CodePipeline, allow AWS to create
their service roles, or provide equivalent least-privilege roles. CodeBuild
needs CloudWatch Logs access and read/write access to the pipeline artifact
bucket. CodePipeline needs access to its artifact bucket, the GitHub
connection, CodeBuild, and CodeDeploy. Do not give the build role access to
application secrets; this build only installs dependencies and validates the
source.

## 3. Create a security group

The instance serves HTTP directly on port 8000 for this initial test.

1. In the VPC you will use for the instance, create a security group with
   outbound internet access so the instance can install packages and download
   CodeDeploy revisions. The default outbound rule is sufficient for a
   straightforward test.
2. Add inbound TCP **8000** with the source set to **My IP** (your current
   public IP in CIDR form, usually `/32`). Do not expose this port to the
   whole internet (`0.0.0.0/0`).
3. For administration, prefer Systems Manager Session Manager. If you use SSH
   instead, add inbound TCP 22 restricted to **My IP** and use your key pair.

## 4. Launch and prepare the EC2 instance

1. Launch **Amazon Linux 2023 AMI** as one EC2 instance. Choose a small
   general-purpose instance for the initial test; image processing and
   concurrent requests may require a larger instance later.
2. Attach the EC2 instance role from step 2, the EC2 security group from step
   3, and a tag that will identify this app, for example `App=StyleSpectrum`.
   Enable a public IPv4 address so you can open the test site directly.
3. Add the following as EC2 user data, changing `REGION` if needed. This
   installs CodeDeploy Agent and the runtime/system packages used by the
   deployment hooks. Ensure outbound access is available during first boot.

   ```bash
   #!/bin/bash
   set -euxo pipefail
   REGION=ap-south-2

   dnf install -y ruby wget python3.11 python3.11-pip curl libgomp mesa-libGL

   cd /tmp
   wget "https://aws-codedeploy-${REGION}.s3.${REGION}.amazonaws.com/latest/install"
   chmod +x ./install
   ./install auto
   systemctl enable codedeploy-agent
   systemctl start codedeploy-agent
   ```

4. In the EC2 console, verify the instance is running and the
   `codedeploy-agent` service is active before continuing.
5. Create `/etc/stylespectrum/stylespectrum.env` on the instance if the S3
   bucket or Region differs from the app defaults. Use Session Manager or
   another secure administrative method:

   ```ini
   S3_BUCKET_NAME=your-image-bucket
   AWS_REGION=ap-south-2
   ```

   Set file ownership to `root:root` and mode to `0600`. These values are
   configuration, not AWS credentials. The systemd unit reads this optional
   file; no pipeline secret is required for S3 access.
6. Copy the instance's public IPv4 address; you will use it to test the
   application after the pipeline deploys.

## 5. Create the CodeDeploy application and deployment group

1. In CodeDeploy, create an application named `stylespectrum` and choose
   **EC2/On-premises** as the compute platform.
2. Create a deployment group, for example `stylespectrum-production`.
3. Select the CodeDeploy service role from step 2.
4. Select **In-place** deployment and identify the EC2 instance by the tag
   `App=StyleSpectrum` (or the tag value you used).
5. Do not configure a load balancer or Auto Scaling group. Save the deployment
   group and confirm CodeDeploy sees the instance as a valid
   target and that its agent is online.

## 6. Create the CodeBuild project

1. Create a CodeBuild project with GitHub as its source provider, or select
   **CodePipeline** as the source if the pipeline will pass the source
   revision.
2. Use a managed Ubuntu standard build image that supports Python 3.11. Select
   Linux, a suitable small/medium compute size, and the CodeBuild role from
   step 2.
3. Set the buildspec filename to `buildspec.yml` at the repository root.
   The buildspec installs `Backend/requirements.txt`, compiles the Python
   source, imports the model to verify both Excel datasets load, and publishes
   `appspec.yml`, the hooks, and `Backend/` as the deployment artifact.
4. Do not configure a test/build output directory as the CodeDeploy artifact;
   CodeDeploy needs the repository artifact containing `appspec.yml` at its
   root.
5. Save the project. A manual build can be used to confirm dependencies and
   model data validation pass before configuring the full pipeline.

## 7. Create the CodePipeline

1. Create a pipeline in the same Region as CodeDeploy and CodeBuild. Let
   CodePipeline create its S3 artifact store or select a private bucket in that
   Region.
2. **Source stage:** choose GitHub through AWS CodeConnections, authorize the
   connection, then select this repository and the branch to deploy. Enable
   change detection so pushes to that branch start the pipeline.
3. **Build stage:** select the CodeBuild project created in step 6. Configure
   the build action's output artifact (for example, `BuildArtifact`).
4. **Deploy stage:** select AWS CodeDeploy, application `stylespectrum`, and
   deployment group `stylespectrum-production`. Use the artifact produced by
   the build stage.
5. Review the pipeline role permissions and create the pipeline. Push a small
   source change or choose **Release change** to run the first deployment.
6. Follow the source, build, and deploy action output in CodePipeline. Fix
   failed actions before promoting the revision; do not treat a successful
   build as proof that the instance has healthy S3 access.

## 8. Test the deployment

1. Open `http://EC2_PUBLIC_IP:8000/` in your browser. The app is served over
   plain HTTP for this minimal test; no DNS name or TLS certificate is needed.
2. Open `http://EC2_PUBLIC_IP:8000/api/health`. A healthy response has HTTP
   200, `"ok": true`, and the expected seasons. If it returns 503, inspect
   the response's `problems` field and the instance service logs before
   retrying.
3. Test image analysis by uploading an image. The browser camera usually
   requires HTTPS (except on localhost), so camera access is not expected to
   work on this direct-HTTP test deployment.
4. Confirm product images load. If analysis works but suggestion images do
   not, check `S3_BUCKET_NAME`, `AWS_REGION`, the object key prefix, the
   instance role's `s3:GetObject` permission, and the bucket Region.
5. Check CodePipeline for the deployed commit and CodeDeploy for successful
   lifecycle hooks.

## 9. Normal releases and operations

- Every push to the configured branch runs the pipeline. CodeBuild is the
  gate; CodeDeploy runs `scripts/install_dependencies.sh`, then starts and
  health-checks the `stylespectrum` systemd service.
- To roll back, redeploy a previously successful pipeline revision or use
  CodeDeploy's deployment history. The instance is directly internet
  reachable on port 8000 from the IPs allowed by its security group.
- Use `sudo systemctl status stylespectrum` and
  `sudo journalctl -u stylespectrum --no-pager -n 100` on the instance to
  diagnose application startup. Use `sudo systemctl status codedeploy-agent`
  and `/var/log/aws/codedeploy-agent/codedeploy-agent.log` for agent issues.
- Keep S3 public access blocked and use IAM roles instead of long-lived keys.
  This setup is intended for a first deployment test, not a production
  internet-facing service. Add HTTPS before enabling camera access or using
  the app publicly.

## What changed in this repository for deployment

- Corrected the dataset directory's case so it loads on Linux.
- Added the missing `python-dotenv` and production `gunicorn` dependencies and
  selected headless OpenCV for server deployment.
- Implemented CodeDeploy hooks to install the virtual environment, create and
  start the systemd service, and verify `/api/health`.
- Made an unhealthy local app/data setup return HTTP 503 for deployment and
  health checks, and disabled Flask debug mode.
