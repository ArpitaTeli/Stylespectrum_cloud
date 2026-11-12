from s3_utils import list_s3_images, get_image_url

try:
    images = list_s3_images()

    print("\nImages found in S3:")

    for image in images:
        print(image)

    if images:
        print("\nTesting image URL...")
        print(get_image_url(images[0]))

    else:
        print("\nNo images found. Check your S3 bucket.")

except Exception as e:
    print("S3 connection failed:", e)