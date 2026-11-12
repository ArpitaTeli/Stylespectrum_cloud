from s3_utils import get_image_url

key = "stylespectrum_img/burn3.png"

try:
    url = get_image_url(key)

    if url:
        print("\nGenerated image URL successfully.")
        print("Open this URL in your browser to test the image:")
        print(url)
    else:
        print("Failed to generate image URL.")

except Exception as e:
    print("Error:", repr(e))