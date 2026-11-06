import frappe
import requests
from frappe.rate_limiter import rate_limit
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

VIDEO_EXTENSIONS = (".mp4", ".webm", ".mov", ".m4v", ".ogv", ".ogg")


@frappe.whitelist(allow_guest=True, methods=["GET"])
@rate_limit(limit=60, seconds=60)
def get_album_images(website_item=None):
	"""Return thumbnail and full-size URLs for a Website Item's Chevereto album."""
	try:
		payload = _fetch_album(website_item)
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


def _gallery_credentials():
	"""Read the Chevereto endpoint and API token from Chevereto Settings."""
	settings = frappe.get_single("Chevereto Settings")
	endpoint = (settings.chevereto_endpoint or "").strip()
	token = settings.get_password("chevereto_api_token", raise_exception=False)
	if not endpoint or not token:
		return None
	return endpoint, token


def _album_name(website_item):
	"""Return the album name stored on a visible Website Item."""
	if not website_item:
		return None
	row = frappe.db.get_value(
		"Website Item",
		website_item,
		["custom_chevereto_album", "published"],
		as_dict=True,
	)
	if not row:
		return None
	if not row.published and not frappe.has_permission("Website Item", "read", doc=website_item):
		return None
	return (row.custom_chevereto_album or "").strip() or None


def _fetch_album(website_item):
	album_name = _album_name(website_item)
	credentials = _gallery_credentials()
	if not album_name or not credentials:
		return {"albums": []}
	endpoint, token = credentials
	url = _album_url(endpoint, album_name)
	try:
		response = _get(url, token)
	except requests.ConnectionError:
		gateway_url = _gateway_url(url)
		if not gateway_url:
			raise
		response = _get(gateway_url, token)
	response.raise_for_status()
	payload = response.json()
	if payload.get("status_code") != 200:
		return {"albums": []}
	return payload


def _album_url(endpoint, album_name):
	query = urlencode({"name": album_name}, quote_via=quote)
	return endpoint.rstrip("/") + "/?" + query


def _get(url, token):
	response = requests.get(
		url,
		headers={"X-API-Key": token},
		timeout=8,
		allow_redirects=False,
	)
	if response.is_redirect:
		location = response.headers.get("Location")
		if location:
			response = requests.get(
				_keep_connection_host(url, location),
				headers={"X-API-Key": token},
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
