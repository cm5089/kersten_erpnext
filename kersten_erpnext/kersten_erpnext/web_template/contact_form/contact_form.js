// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// MIT License. See license.txt

frappe.ready(function() {
	$('.btn-send').off("click").on("click", function() {
		var email = $('[name="email"]').val();
		var message = $('[name="message"]').val();
		var first_name = $('[name="first_name"]').val();
		var last_name = $('[name="last_name"]').val();
		var url = $('[name="url"]').val();
		var organisation_name = $('[name="organisation_name"]').val();
		var mobile_no = $('[name="mobile_no"]').val();

		if(!(first_name && last_name && email)) {
			frappe.msgprint('{{ _("Please enter your First Name, Last Name and Email so that we can get back to you. Thanks!") }}');
			return false;
		}

		if(!validate_email(email)) {
			frappe.msgprint('{{ _("You seem to have written your name instead of your email. Please enter a valid email address so that we can get back.") }}');
			$('[name="email"]').focus();
			return false;
		}

		$("#contact-alert").toggle(false);
		frappe.call({
			method:"kersten_erpnext.kersten_erpnext.web_template.contact_form.contact_form.send_message",
			args: {
				sender: email,
				message: message,
				first_name: first_name,
				last_name: last_name,
				url: url,
				mobile_no: mobile_no,
				organisation_name: organisation_name
			},
			callback: function(r) {
				if (!r.exc) {
					frappe.msgprint('{{ _("Thank you for your message") }}');
				}
				$(':input').val('');
			}
		},this)
		return false;
	});

});

var msgprint = function(txt) {
	if(txt) $("#contact-alert").html(txt).toggle(true);
}