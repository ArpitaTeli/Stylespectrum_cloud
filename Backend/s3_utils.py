
import os
import boto3
from dotenv import load_dotenv
from botocore.config import Config

# Load environment variables
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "stylespectrum").strip()
AWS_REGION = os.getenv("AWS_REGION", "ap-south-2").strip()

# Explicitly configure the regional S3 endpoint.
s3_client = boto3.client(
    "s3",
    region_name=AWS_REGION,
    endpoint_url=f"https://s3.{AWS_REGION}.amazonaws.com",
    config=Config(
        signature_version="s3v4",
        s3={"addressing_style": "virtual"}
    )
)


def list_s3_images():
    """List images inside the S3 image folder."""
    paginator = s3_client.get_paginator("list_objects_v2")
    images = []

    for page in paginator.paginate(
        Bucket=BUCKET_NAME,
        Prefix="stylespectrum_img/"
    ):
        for obj in page.get("Contents", []):
            key = obj["Key"]

            if key.lower().endswith(
                (".png", ".jpg", ".jpeg", ".webp", ".gif")
            ):
                images.append(key)

    return images


def get_image_url(s3_key):
    """Generate a presigned URL using the correct S3 region."""
    if not s3_key:
        return None

    s3_key = str(s3_key).strip().replace("\\", "/").lstrip("/")

    if not s3_key.startswith("stylespectrum_img/"):
        s3_key = f"stylespectrum_img/{s3_key}"

    return s3_client.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": BUCKET_NAME,
            "Key": s3_key
        },
        ExpiresIn=3600
    )


if __name__ == "__main__":
    print("Bucket:", BUCKET_NAME)
    print("Region:", AWS_REGION)

    try:
        images = list_s3_images()
        print(f"Found {len(images)} images.")

        test_key = "stylespectrum_img/burn3.png"
        print("Testing:", test_key)

        url = get_image_url(test_key)
        print("Generated URL. Open it in your browser to test the image.")
        print(url)

    except Exception as error:
        print("Error:", repr(error))
