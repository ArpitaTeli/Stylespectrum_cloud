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
