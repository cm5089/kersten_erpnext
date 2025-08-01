# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

from contextlib import suppress

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import validate_email_address
from frappe.model.mapper import get_mapped_doc
from frappe.core.doctype.file.utils import extract_images_from_html
from frappe.desk.form.document_follow import follow_document



sitemap = 1


def get_context(context):
	doc = frappe.get_doc("Contact Us Settings", "Contact Us Settings")

	if doc.query_options:
		query_options = [opt.strip() for opt in doc.query_options.replace(",", "\n").split("\n") if opt]
	else:
		query_options = ["Sales", "Support", "General"]

	out = {"query_options": query_options, "parents": [{"name": _("Home"), "route": "/"}]}
	out.update(doc.as_dict())

	return out


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=1000, seconds=60 * 60)
def send_message(sender, message, first_name=None, last_name=None, mobile_no=None, postal_code=None, organisation_name=None, subject="Website Query"):
	sender = validate_email_address(sender, throw=True)

	with suppress(frappe.OutgoingEmailError):
		if forward_to_email := frappe.db.get_single_value("Contact Us Settings", "forward_to_email"):
			frappe.sendmail(recipients=forward_to_email, reply_to=sender, content=message, subject=subject)

		frappe.sendmail(
			recipients=sender,
			content=f"<div style='white-space: pre-wrap'>Thank you for reaching out to us. We will get back to you at the earliest.\n\n\nYour query:\n\n{message}</div>",
			subject="We've received your query!",
		)

	# Check if contact is already linked to a Lead
	contact_data = frappe.db.sql("""
		SELECT co.name, dl.link_name
		FROM `tabContact` co
		LEFT JOIN `tabContact Email` ce ON ce.parent = co.name
		LEFT JOIN `tabDynamic Link` dl ON dl.parent = co.name
		WHERE ce.email_id = %s AND dl.link_doctype = 'Lead'
	""", (sender,), as_dict=1)

	if contact_data:
		doc = frappe.new_doc("Opportunity")
		doc.opportunity_from = "Lead"
		doc.party_name = contact_data[0].link_name
		doc.contact_mobile = mobile_no
		doc.contact_email = sender
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		doc.save()
		add_comment("Opportunity", doc.name, content=message, comment_email=sender, comment_by=None)
		return

	# Check if contact exists but no linked Lead
	contact_but_no_lead = frappe.db.sql("""
		SELECT co.name FROM `tabContact` co
		LEFT JOIN `tabContact Email` ce ON ce.parent = co.name
		WHERE ce.email_id = %s
	""", (sender,), as_dict=1)

	# Check if Customer exists
	customer_exists = frappe.db.exists("Customer", {"customer_name": organisation_name})

	if customer_exists:
		# Check if contact is already linked to this customer
		contact_name = frappe.db.get_value("Dynamic Link", {
			"link_doctype": "Customer",
			"link_name": organisation_name,
			"parenttype": "Contact"
		}, "parent")

		# If not found, create contact
		if not contact_name:
			contact = frappe.new_doc("Contact")
			contact.first_name = first_name or sender
			contact.last_name = last_name
			contact.email_id = sender
			contact.mobile_no = mobile_no
			contact.append("email_ids", {
				"email_id": sender,
				"is_primary": 1
			})
			contact.append("phone_nos", {
				"phone": mobile_no,
				"is_primary_phone": 1
			})
			contact.append("links", {
				"link_doctype": "Customer",
				"link_name": organisation_name
			})
			contact.flags.ignore_mandatory = True
			contact.insert(ignore_permissions=True)
			contact_name = contact.name

		# Create opportunity for Customer
		opportunity = frappe.new_doc("Opportunity")
		opportunity.opportunity_from = "Customer"
		opportunity.party_name = organisation_name
		opportunity.contact_email = sender
		opportunity.contact_mobile = mobile_no
		opportunity.contact_phone = mobile_no
		opportunity.contact_person = contact_name
		opportunity.customer_application = "Website"
		opportunity.source = "Contact Form Submission"
		opportunity.flags.ignore_permissions = True
		opportunity.flags.ignore_mandatory = True
		opportunity.insert(ignore_permissions=True)

		add_comment("Opportunity", opportunity.name, content=message, comment_email=sender, comment_by=frappe.session.user)

	else:
		# Create Lead and linked Contact
		lead = frappe.new_doc("Lead")
		lead.first_name = first_name
		lead.last_name = last_name
		lead.email_id = sender
		lead.company_name = organisation_name
		lead.flags.ignore_mandatory = True
		lead.save(ignore_permissions=True)

		opportunity = frappe.new_doc("Opportunity")
		opportunity.opportunity_from = "Lead"
		opportunity.party_name = lead.name
		opportunity.contact_email = sender
		opportunity.contact_mobile = mobile_no
		opportunity.source = "Contact Form Submission"
		opportunity.flags.ignore_permissions = True
		opportunity.flags.ignore_mandatory = True
		opportunity.save(ignore_permissions=True)

		add_comment("Opportunity", opportunity.name, content=message, comment_email=sender, comment_by=frappe.session.user)

		contact = frappe.new_doc("Contact")
		contact.first_name = first_name
		contact.last_name = last_name
		contact.email_id = sender
		contact.mobile_no = mobile_no
		contact.append("email_ids", {
			"email_id": sender,
			"is_primary": 1
		})
		contact.append("links", {
			"link_doctype": "Lead",
			"link_name": lead.name
		})
		contact.append("phone_nos", {
			"phone": mobile_no,
			"is_primary_phone": 1
		})
		contact.flags.ignore_mandatory = True
		contact.save(ignore_permissions=True)

		

	

def add_comment(reference_doctype: str, reference_name: str, content: str, comment_email: str, comment_by: str):
	reference_doc = frappe.get_doc(reference_doctype, reference_name)

	comment = frappe.new_doc("Comment")
	comment.update(
		{
			"comment_type": "Comment",
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"comment_email": comment_email,
			"comment_by": comment_by,
			"content": extract_images_from_html(reference_doc, content, is_private=True),
		}
	)
	comment.insert(ignore_permissions=True)

	if frappe.get_cached_value("User", frappe.session.user, "follow_commented_documents"):
		follow_document(comment.reference_doctype, comment.reference_name, frappe.session.user)

	return comment