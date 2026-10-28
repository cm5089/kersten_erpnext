// Use frappe.ready to ensure frappe global object is fully populated.
// Dialog is created lazily on first click so frappe.ui.Dialog is always available.
frappe.ready(() => {
	let inquiry_dialog = null;

	function get_or_create_dialog() {
		if (inquiry_dialog) return inquiry_dialog;

		inquiry_dialog = new frappe.ui.Dialog({
			title: __('Contact Us'),
			fields: [
				{
					fieldtype: 'Data',
					label: __('Full Name'),
					fieldname: 'lead_name',
					reqd: 1
				},
				{
					fieldtype: 'Data',
					label: __('Organization Name'),
					fieldname: 'company_name',
				},
				{
					fieldtype: 'Data',
					label: __('Email'),
					fieldname: 'email_id',
					options: 'Email',
					reqd: 1
				},
				{
					fieldtype: 'Data',
					label: __('Phone Number'),
					fieldname: 'phone',
					options: 'Phone',
					reqd: 1
				},
				{
					fieldtype: 'Data',
					label: __('Subject'),
					fieldname: 'subject',
					reqd: 1
				},
				{
					fieldtype: 'Text',
					label: __('Message'),
					fieldname: 'message',
					reqd: 1
				}
			],
			primary_action: send_inquiry,
			primary_action_label: __('Send')
		});

		return inquiry_dialog;
	}

	function send_inquiry() {
		const d = inquiry_dialog;
		const values = d.get_values();
		if (!values) return;

		const doc = Object.assign({}, values);
		delete doc.subject;
		delete doc.message;

		// Hide first, then call — so user gets immediate feedback
		d.hide();

		frappe.call('kersten.api.create_lead_for_item_inquiry', {
			lead: doc,
			subject: values.subject,
			message: values.message
		}).then(r => {
			if (r && r.message) {
				d.clear();
			}
		}).catch(() => {
			// Show error to user if submission fails instead of silent disappear
			frappe.msgprint(__('Sorry, there was an error submitting your enquiry. Please try again.'));
		});
	}

	// Use event delegation so it works even if btn is rendered dynamically
	$(document).on('click', '.btn-inquiry', (e) => {
		const $btn = $(e.currentTarget);
		const item_code = $btn.data('item-code');

		const d = get_or_create_dialog();
		d.clear();
		d.set_value('subject', 'Inquiry about ' + item_code);

		// Only pre-fill logged-in (non-guest) users — never overwrite with stale cookies
		const user = frappe.session && frappe.session.user;
		if (user && !['Administrator', 'Guest'].includes(user)) {
			d.set_value('email_id', user);
			const full_name = frappe.get_cookie('full_name');
			if (full_name && full_name !== 'Guest' && full_name.trim()) {
				d.set_value('lead_name', decodeURIComponent(full_name));
			}
		}

		d.show();
	});
});
