import frappe
import requests
from frappe.rate_limiter import rate_limit
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit

VIDEO_EXTENSIONS = (".mp4", ".webm", ".mov", ".m4v", ".ogv", ".ogg")


@frappe.whitelist(allow_guest=True, methods=["GET"])
@rate_limit(limit=60, seconds=60)
def get_album_images(website_item=None):
	"""Return Website Item images, then Chevereto media, then its YouTube videos."""
	images = _erpnext_images(website_item)
	try:
		images.extend(_chevereto_images(website_item))
	except requests.RequestException:
		frappe.log_error(title="Product gallery request failed")
	except frappe.DoesNotExistError:
		pass
	images.extend(_youtube_images(website_item))
	return {"images": _dedupe(images)}


def _visible_website_item(website_item):
	if not website_item:
		return None
	row = frappe.db.get_value(
		"Website Item",
		website_item,
		["custom_chevereto_album", "published", "website_image", "slideshow"],
		as_dict=True,
	)
	if not row:
		return None
	if not row.published and not frappe.has_permission("Website Item", "read", doc=website_item):
		return None
	return row


def _erpnext_images(website_item):
	"""Product image first, then each public slide from the Website Slideshow."""
	row = _visible_website_item(website_item)
	if not row:
		return []

	images = []
	product_image = _image_record(row.website_image)
	if product_image:
		images.append(product_image)
	if not row.slideshow:
		return images

	slides = frappe.get_all(
		"Website Slideshow Item",
		filters={"parent": row.slideshow, "parenttype": "Website Slideshow"},
		fields=["image"],
		order_by="idx asc",
	)
	for slide in slides:
		image = _image_record(slide.image)
		if image:
			images.append(image)
	return images


def _image_record(url):
	cleaned = _media_url(url)
	if not cleaned:
		return None
	return {"thumbnail": cleaned, "direct": cleaned, "type": "image"}


def _chevereto_images(website_item):
	payload = _fetch_album(website_item)
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
	return images


def _dedupe(images):
	unique = []
	seen = set()
	for image in images:
		key = _image_key(image.get("direct") or image.get("thumbnail"))
		if not key or key in seen:
			continue
		seen.add(key)
		unique.append(image)
	return unique


def _image_key(url):
	parts = urlsplit(url or "")
	if not parts.path:
		return None
	return (parts.path, parts.query)


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
	row = _visible_website_item(website_item)
	if not row:
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


def _media_url(value):
	"""Accept a public http(s) URL or a site-relative file path."""
	if not isinstance(value, str):
		return None
	value = value.strip()
	if value.startswith(("http://", "https://")) or (value.startswith("/") and not value.startswith("//")):
		return value
	return None


def _http_url(value):
	cleaned = _media_url(value)
	if cleaned and (cleaned.startswith("http://") or cleaned.startswith("https://")):
		return cleaned
	return None


def _youtube_images(website_item):
	"""Return one gallery item for each YouTube URL on the Website Item."""
	if not _visible_website_item(website_item):
		return []
	links = frappe.get_all(
		"YouTube Link",
		filters={
			"parent": website_item,
			"parenttype": "Website Item",
			"parentfield": "custom_youtube_videos",
		},
		fields=["youtube_url"],
		order_by="idx asc",
	)
	images = []
	for link in links:
		video = _youtube_record(link.youtube_url)
		if video:
			images.append(video)
	return images


def _youtube_record(url):
	video_id = _youtube_id(url)
	if not video_id:
		return None
	return {
		"thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
		"direct": f"https://www.youtube.com/embed/{video_id}",
		"type": "youtube",
	}


def _youtube_id(url):
	parts = urlsplit(url or "")
	host = parts.netloc.lower().removeprefix("www.")
	video_id = None
	if host == "youtu.be":
		video_id = parts.path.strip("/").split("/")[0]
	elif host in ("youtube.com", "m.youtube.com", "youtube-nocookie.com"):
		if parts.path == "/watch":
			video_id = (parse_qs(parts.query).get("v") or [None])[0]
		elif parts.path.startswith(("/embed/", "/shorts/", "/live/")):
			pieces = [piece for piece in parts.path.split("/") if piece]
			video_id = pieces[1] if len(pieces) > 1 else None
	if video_id and len(video_id) == 11 and video_id.replace("-", "").replace("_", "").isalnum():
		return video_id
	return None


def _media_type(url):
	path = urlsplit(url or "").path.lower()
	if path.endswith(VIDEO_EXTENSIONS):
		return "video"
	return "image"
