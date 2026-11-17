# Deploy with AWS Elastic Beanstalk

This repository is a single Flask application. The browser UI, API, local
assets, and datasets are all under `Backend/`; product suggestion images are
served from a private S3 bucket. There is no separate frontend build step.

The ZIP downloaded from GitHub is a repository archive, not an Elastic
Beanstalk source bundle: it has an extra top-level folder. Build a flat
deployment ZIP from the extracted repository before using Elastic Beanstalk's
**Upload and deploy** option.

## 1. Download and prepare the source bundle

1. Download the repository ZIP from GitHub and extract it.
2. Open a terminal in the extracted repository folder (the folder containing
   `Backend/` and `scripts/`).
3. Run the included ZIP builder. It uses only Python's standard library; it
   does not install or run the application.

   ```bash
   python3 scripts/create_eb_bundle.py
   ```

   On Windows, use `py scripts/create_eb_bundle.py`. The command creates
   `stylespectrum-eb.zip` in the repository folder. This ZIP has `Procfile`,
   `requirements.txt`, and `Backend/` at its root, as Elastic Beanstalk
   expects. It excludes local `.env` files, uploaded images, and Python cache
   files. Do not upload the original GitHub archive.

## 2. Prepare product images and the instance role

The product suggestion images must be in a private S3 bucket under the
`stylespectrum_img/` prefix. For example, from the repository folder:

```bash
aws s3 sync Backend/static/images/ s3://YOUR_BUCKET/stylespectrum_img/ \
  --region YOUR_REGION
```

In IAM, create or select an EC2 instance profile for the Elastic Beanstalk
environment. Grant it `s3:GetObject` only for
`arn:aws:s3:::YOUR_BUCKET/stylespectrum_img/*`, replacing `YOUR_BUCKET` with
the bucket name. Keep S3 Block Public Access enabled. Do not put AWS access
keys in the deployment ZIP or Elastic Beanstalk environment properties.

## 3. Create and deploy the Elastic Beanstalk environment

1. In Elastic Beanstalk, create an application and a **Web server environment**.
2. Choose the **Python 3.11** platform on Amazon Linux 2023.
3. Select or create the Elastic Beanstalk service role and attach the EC2
   instance profile from step 2 to the environment's instances.
4. In the environment configuration, set these software environment
   properties:

   ```text
   S3_BUCKET_NAME=YOUR_BUCKET
   AWS_REGION=YOUR_REGION
   ```

5. Create the environment. When it is ready, open the environment and choose
   **Upload and deploy**. Select `stylespectrum-eb.zip` and deploy it. The
   root `Procfile` starts Gunicorn, and the root `requirements.txt` installs
   the packages listed in `Backend/requirements.txt`.

## 4. Verify

Open the environment URL shown in the Elastic Beanstalk console. Check:

- `/` loads the StyleSpectrum interface.
- `/api/health` returns HTTP 200 with `"ok": true` and the expected seasons.
- Image analysis works and suggestion images load from S3.

If health returns 503, inspect the response's `problems` field and the
environment logs. If suggestion images do not load, verify the bucket name,
Region, S3 object prefix, and instance-profile permission.

Elastic Beanstalk's public environment URL uses HTTPS, which also allows the
browser camera feature. Review AWS charges and configure environment access
and scaling to suit your use before sharing the URL publicly.

## 5. Create a CodePipeline without a build stage

The pipeline can deploy the GitHub source artifact directly to your existing
Elastic Beanstalk application and environment. This avoids CodeBuild usage and
quotas. Make sure the selected branch already contains the root `Procfile`,
root `requirements.txt`, and the `Backend/` application directory. The source
artifact must have those paths at its root; do not use the GitHub
**Download ZIP** archive, which adds an extra top-level folder.

Confirm the Elastic Beanstalk environment is healthy and its S3 environment
properties and instance-role permissions are set as described above.

1. In AWS, open **CodePipeline** in the same Region as your Elastic Beanstalk
   environment and choose **Create pipeline**. Choose **Build custom pipeline**.
   Enter a pipeline name and let the wizard create a new service role and
   artifact store.
2. In **Source**, choose **GitHub (via GitHub App)**. Choose **Connect to
   GitHub**, authorize/install the AWS Connector app for this repository, then
   select `ArpitaTeli/Stylespectrum_cloud` and the branch to deploy (for
   example, `main`). Enable push change detection so commits start the
   pipeline automatically.
3. Skip the **Build** stage. Add a **Deploy** stage, choose **AWS Elastic
   Beanstalk**, then select the existing application and environment. Set the
   GitHub source action's output artifact as the deploy action's input.
4. Review the settings and create the pipeline. Allow the wizard to create
   the CodePipeline service role and artifact store. Watch the first execution;
   if it does not start automatically, choose **Release change**.

After a successful first run, pushes to the selected branch build and deploy
automatically, with no CodeBuild stage involved. The Elastic Beanstalk
environment health and logs show deployment/runtime failures. Keep the
environment's S3 settings and IAM instance permissions in place. Manual
**Upload and deploy** remains available, but avoid using it while a pipeline
execution is in progress. Since there is no build stage, run validation
before pushing if you need a pre-deployment check.
