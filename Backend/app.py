import os
import sys
from flask import Flask, request, jsonify, render_template
from s3_utils import get_image_url
from werkzeug.utils import secure_filename
from botocore.exceptions import ClientError

# Resolve paths relative to this file.
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Import the model and report import errors clearly.
try:
    import model
    analyze_image_and_get_data = model.analyze_image_and_get_data
except Exception as e:
    print(f"FATAL: Could not import model.py: {e}", file=sys.stderr)
    model = None
    analyze_image_and_get_data = None

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB upload limit

UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# These are local UI assets, not product suggestion images in S3.
EXPECTED_STATIC = [
    "smile_please.png",
    "spring.png",
    "summer.png",
    "autumn.png",
    "winter.png",
]


def _image_url(path):
    """
    Convert an Image Path value from suggestions.xlsx into a presigned S3 URL.

    Examples:
      jetblack.png                       -> stylespectrum_img/jetblack.png
      images/jetblack.png                -> stylespectrum_img/jetblack.png
      static/images/jetblack.png         -> stylespectrum_img/jetblack.png
      stylespectrum_img/jetblack.png     -> stylespectrum_img/jetblack.png

    Complete HTTP/HTTPS URLs are returned unchanged.
    """
    if path is None:
        return None

    path = str(path).strip().replace("\\", "/")
    if not path or path.lower() in ("nan", "none", "null"):
        return None

    if path.lower().startswith(("http://", "https://")):
        return path

    # Remove any old local path prefixes.
    lowered = path.lower()
    for prefix in ("static/images/", "static/", "images/"):
        if lowered.startswith(prefix):
            path = path[len(prefix):]
            break

    prefix = "stylespectrum_img/"
    if path.lower().startswith(prefix.lower()):
        # Normalize the prefix capitalization but preserve the filename.
        s3_key = prefix + path[len(prefix):].lstrip("/")
    else:
        s3_key = prefix + path.lstrip("/")

    try:
        url = get_image_url(s3_key)
        if not url:
            print(
                f"WARNING: No S3 URL returned for image key {s3_key!r}",
                file=sys.stderr
            )
            return None

        # Do not log the full presigned URL because it contains temporary
        # signature parameters. Log only the object key.
        print(f"S3 URL generated for image key: {s3_key}")
        return url

    except ClientError as e:
        print(
            f"S3 ClientError for image key {s3_key!r}: {e}",
            file=sys.stderr
        )
        return None
    except Exception as e:
        print(
            f"Could not create S3 URL for key {s3_key!r}: {e}",
            file=sys.stderr
        )
        return None


def startup_report():
    """Return local app/data setup problems."""
    problems = []

    if model is None:
        problems.append(
            "model.py could not be imported; check dependencies and server console"
        )
    elif getattr(model, "palette_data", None) is None or getattr(
        model, "suggestions", None
    ) is None:
        problems.append(
            "Datasets not loaded; check Datasets/color_palate_ds.xlsx "
            "and Datasets/suggestions.xlsx"
        )

    if not os.path.exists(os.path.join(BASE_DIR, "templates", "index.html")):
        problems.append("templates/index.html is missing")

    for name in EXPECTED_STATIC:
        if not os.path.exists(os.path.join(BASE_DIR, "static", name)):
            problems.append(f"static/{name} is missing")

    return problems


@app.route("/")
def index():
    """Serve the main HTML page."""
    return render_template("index.html")


@app.route("/api/health")
def health():
    """Check local app/data setup at http://localhost:5000/api/health."""
    problems = startup_report()

    return jsonify({
        "ok": not problems,
        "problems": problems,
        "seasons_in_palette": (
            sorted(model.palette_data["Season"].dropna().unique().tolist())
            if model is not None
            and getattr(model, "palette_data", None) is not None
            and "Season" in model.palette_data.columns
            else []
        ),
        "suggestion_image_source": "Amazon S3 presigned URLs",
        "s3_bucket": os.getenv("S3_BUCKET_NAME", "stylespectrum"),
        "s3_region": os.getenv("AWS_REGION", "ap-south-2"),
        "s3_prefix": "stylespectrum_img/",
    }), (200 if not problems else 503)


@app.route("/api/analyze_image", methods=["POST"])
def analyze_image():
    """Analyze an uploaded/captured image and return S3 suggestion URLs."""
    if analyze_image_and_get_data is None:
        return jsonify({
            "error": (
                "Analysis service is unavailable because model.py failed to load. "
                "Check the server console."
            )
        }), 503

    if "image" not in request.files:
        return jsonify({"error": "No image file was received."}), 400

    file = request.files["image"]
    if not file or file.filename == "":
        return jsonify({"error": "Empty file name."}), 400

    file_path = None

    try:
        filename = secure_filename(file.filename) or "upload.png"
        file_path = os.path.join(
            UPLOAD_FOLDER, f"{os.urandom(8).hex()}_{filename}"
        )
        file.save(file_path)

        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            return jsonify({
                "error": "The image arrived empty. Please try again."
            }), 400

        results, error = analyze_image_and_get_data(file_path)
        if error or not results:
            return jsonify({
                "error": error or "Analysis returned no result."
            }), 500

        # Normalize all suggestion image paths before returning the response.
        suggestions = results.get("suggestions") or []
        for item in suggestions:
            original_path = item.get("image_path")
            item["image_path"] = _image_url(original_path)

            # Helpful diagnostic that doesn't expose the presigned URL.
            if not item["image_path"]:
                print(
                    "WARNING: Suggestion image URL is empty. "
                    f"Original Image Path={original_path!r}, "
                    f"style={item.get('style')!r}, "
                    f"gender={item.get('gender')!r}",
                    file=sys.stderr
                )

        # Return after processing every suggestion (not inside the loop).
        return jsonify(results), 200

    except Exception as e:
        print(f"Server error during analysis: {e}", file=sys.stderr)
        return jsonify({
            "error": f"Unexpected server error: {e}"
        }), 500

    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                print(
                    f"Error cleaning up uploaded file {file_path}: {e}",
                    file=sys.stderr
                )


@app.errorhandler(413)
def too_large(_):
    return jsonify({"error": "Image is too large (max 16 MB)."}), 413


if __name__ == "__main__":
    for problem in startup_report():
        print(f"WARNING: {problem}", file=sys.stderr)

    port = int(os.environ.get("PORT", 5000))
    # Camera access works on localhost or HTTPS.
    app.run(host="0.0.0.0", port=port, debug=False)
