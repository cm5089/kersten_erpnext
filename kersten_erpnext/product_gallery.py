import frappe
import requests
from frappe.rate_limiter import rate_limit
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

# Temporary Chevereto settings. Website Item will supply these later.
# The stored album name has two spaces before the final H.
GALLERY_ENDPOINT = "http://localhost:8080/api/1/album"
GALLERY_ALBUM_NAME = "FKM 13060L  H"
GALLERY_API_TOKEN = "a19efe09b5dc6c3407f579fb4cc0ff43ec927fc415f7810d8d4915cdd14de44c"
VIDEO_EXTENSIONS = (".mp4", ".webm", ".mov", ".m4v", ".ogv", ".ogg")


@frappe.whitelist(allow_guest=True, methods=["GET"])
@rate_limit(limit=60, seconds=60)
def get_album_images():
	"""Return thumbnail and full-size URLs for the temporary product album."""
	try:
		payload = _fetch_album()
	except requests.RequestException:
		frappe.log_error(title="Product gallery request failed")
		return {"images": []}

	images = []
	for album in payload.get("albums") or []:
		for image in album.get("images") or []:
			thumbnail = _http_url(image.get("thumbnail"))
			direct = _http_url(image.get("direct"))
			if thumbnail or direct:
				images.append({
					"thumbnail": thumbnail or direct,
					"direct": direct or thumbnail,
					"type": _media_type(direct or thumbnail),
				})
	return {"images": images}


def _fetch_album():
	url = _album_url(GALLERY_ENDPOINT)
	try:
		response = _get(url)
	except requests.ConnectionError:
		gateway_url = _gateway_url(url)
		if not gateway_url:
			raise
		response = _get(gateway_url)
	response.raise_for_status()
	payload = response.json()
	if payload.get("status_code") != 200:
		return {"albums": []}
	return payload


def _album_url(endpoint):
	query = urlencode({"name": GALLERY_ALBUM_NAME}, quote_via=quote)
	return endpoint.rstrip("/") + "/?" + query


def _get(url):
	response = requests.get(
		url,
		headers={"X-API-Key": GALLERY_API_TOKEN},
		timeout=8,
		allow_redirects=False,
	)
	if response.is_redirect:
		location = response.headers.get("Location")
		if location:
			response = requests.get(
				_keep_connection_host(url, location),
				headers={"X-API-Key": GALLERY_API_TOKEN},
				timeout=8,
				allow_redirects=False,
			)
	return response


def _keep_connection_host(original, location):
	"""Stay on the host that answered, instead of following a redirect to localhost."""
	source = urlsplit(original)
	target = urlsplit(location)
	return urlunsplit((source.scheme, source.netloc, target.path, target.query, ""))


def _gateway_url(url):
	"""Reach a host-published port when this process runs inside a container."""
	if "://localhost" not in url and "://127.0.0.1" not in url:
		return None
	gateway = _default_gateway()
	if not gateway:
		return None
	return url.replace("://localhost", f"://{gateway}", 1).replace("://127.0.0.1", f"://{gateway}", 1)


def _default_gateway():
	try:
		with open("/proc/net/route", encoding="ascii") as handle:
			for line in handle:
				fields = line.split()
				if len(fields) >= 3 and fields[1] == "00000000" and len(fields[2]) == 8:
					raw = fields[2]
					return ".".join(str(int(raw[index : index + 2], 16)) for index in (6, 4, 2, 0))
	except OSError:
		return None
	return None


def _http_url(value):
	if isinstance(value, str) and (value.startswith("http://") or value.startswith("https://")):
		return value
	return None


def _media_type(url):
	path = urlsplit(url or "").path.lower()
	if path.endswith(VIDEO_EXTENSIONS):
		return "video"
	return "image"
