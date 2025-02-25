from __future__ import absolute_import

import datetime
import os
from mimetypes import guess_type

from django.conf import settings
from django.template.loader import render_to_string
from django.utils.translation import gettext_lazy as _
from six import PY3, string_types

from .....base import (
    FormHandlerPlugin,
    FormWizardHandlerPlugin,
    get_processed_form_data,
    get_processed_form_wizard_data,
)
from .....helpers import (
    extract_file_path,
    get_form_element_entries_for_form_wizard_entry,
    safe_text,
)
from . import UID
from .forms import MailForm
from .helpers import send_mail
from .mixins import MailHandlerMixin
from .settings import MULTI_EMAIL_FIELD_VALUE_SPLITTER

__title__ = "fobi.contrib.plugins.form_handlers.mail.base"
__author__ = "Artur Barseghyan <artur.barseghyan@gmail.com>"
__copyright__ = "2014-2019 Artur Barseghyan"
__license__ = "GPL 2.0/LGPL 2.1"
__all__ = (
    "MailHandlerPlugin",
    "MailWizardHandlerPlugin",
)

# *****************************************************************************
# **************************** Form handler ***********************************
# *****************************************************************************


class MailHandlerPlugin(FormHandlerPlugin, MailHandlerMixin):
    """Mail handler plugin.

    Sends emails to the person specified. Should be executed before
    ``db_store`` and ``http_repost`` plugins.
    """

    uid = UID
    name = _("Mail")
    form = MailForm

    def run(self, form_entry, request, form, form_element_entries=None):
        """Run.

        :param fobi.models.FormEntry form_entry: Instance of
            ``fobi.models.FormEntry``.
        :param django.http.HttpRequest request:
        :param django.forms.Form form:
        :param iterable form_element_entries: Iterable of
            ``fobi.models.FormElementEntry`` objects.
        """
        base_url = self.get_base_url(request)

        # Clean up the values, leave our content fields and empty values.
        field_name_to_label_map, cleaned_data = get_processed_form_data(
            form, form_element_entries
        )

        rendered_data = self.get_rendered_data(
            cleaned_data, field_name_to_label_map, base_url
        )

        files = self._prepare_files(request, form)

        self.send_email(rendered_data, files)

    def plugin_data_repr(self):
        """Human readable representation of plugin data.

        :return string:
        """
        to_email = None
        # Handling more than one email address
        if isinstance(self.data.to_email, (list, tuple)):
            to_email = "{0} ".format(MULTI_EMAIL_FIELD_VALUE_SPLITTER).join(
                self.data.to_email
            )
        else:
            # Assume that it's string
            to_email = self.data.to_email

        context = {
            "to_name": safe_text(self.data.to_name),
            "to_email": to_email,
            "subject": safe_text(self.data.subject),
        }
        return render_to_string("mail/plugin_data_repr.html", context)


# *****************************************************************************
# ************************ Form wizard handler ********************************
# *****************************************************************************


class MailWizardHandlerPlugin(FormWizardHandlerPlugin):
    """Mail wizard handler plugin.

    Sends emails to the person specified. Should be executed before
    ``db_store`` and ``http_repost`` plugins.
    """

    uid = UID
    name = _("Mail")
    form = MailForm

    def run(
        self,
        form_wizard_entry,
        request,
        form_list,
        form_wizard,
        form_element_entries=None,
    ):
        """Run.

        :param fobi.models.FormWizardEntry form_wizard_entry: Instance
            of :class:`fobi.models.FormWizardEntry`.
        :param django.http.HttpRequest request:
        :param list form_list: List of :class:`django.forms.Form` instances.
        :param fobi.wizard.views.dynamic.DynamicWizardView form_wizard:
            Instance of :class:`fobi.wizard.views.dynamic.DynamicWizardView`.
        :param iterable form_element_entries: Iterable of
            ``fobi.models.FormElementEntry`` objects.
        """
        base_url = "http{secure}://{host}".format(
            secure=("s" if request.is_secure() else ""), host=request.get_host()
        )

        if not form_element_entries:
            form_element_entries = (
                get_form_element_entries_for_form_wizard_entry(
                    form_wizard_entry
                )
            )

        # Clean up the values, leave our content fields and empty values.
        field_name_to_label_map, cleaned_data = get_processed_form_wizard_data(
            form_wizard, form_list, form_element_entries
        )

        rendered_data = []
        for key, value in cleaned_data.items():
            if (
                value
                and isinstance(value, string_types)
                and value.startswith(settings.MEDIA_URL)
            ):
                cleaned_data[key] = "{base_url}{value}".format(
                    base_url=base_url, value=value
                )
            label = field_name_to_label_map.get(key, key)
            rendered_data.append(
                "{0}: {1}\n".format(
                    safe_text(label), safe_text(cleaned_data[key])
                )
            )

        files = self._prepare_files(request, form_list)

        # Handling more than one email address
        if isinstance(self.data.to_email, (list, tuple)):
            to_email = self.data.to_email
        else:
            # Assume that it's string
            to_email = self.data.to_email.split(
                MULTI_EMAIL_FIELD_VALUE_SPLITTER
            )

        send_mail(
            safe_text(self.data.subject),
            "{0}\n\n{1}".format(
                safe_text(self.data.body), "".join(rendered_data)
            ),
            self.data.from_email,
            to_email,
            fail_silently=False,
            attachments=files.values(),
        )

    def _prepare_files(self, request, form_list):
        """Prepares the files for being attached to the mail message."""
        files = {}

        def process_path(file_path, imf):
            """Processes the file path and the file."""
            if file_path:
                # if file_path.startswith(settings.MEDIA_URL):
                #     file_path = file_path[1:]
                # file_path = settings.PROJECT_DIR('../{0}'.format(file_path))
                file_path = file_path.replace(
                    settings.MEDIA_URL, os.path.join(settings.MEDIA_ROOT, "")
                )
                mime_type = guess_type(imf.name)
                if PY3:
                    imf_chunks = b"".join([c for c in imf.chunks()])
                else:
                    imf_chunks = "".join([c for c in imf.chunks()])

                files[field_name] = (
                    imf.name,
                    imf_chunks,
                    mime_type[0] if mime_type else "",
                )

        for form in form_list:
            for field_name, imf in request.FILES.items():
                try:
                    file_path = form.cleaned_data.get(field_name, "")
                    process_path(file_path, imf)
                except Exception as err:
                    file_path = extract_file_path(imf.name)
                    process_path(file_path, imf)

        return files

    def plugin_data_repr(self):
        """Human readable representation of plugin data.

        :return string:
        """
        to_email = None
        # Handling more than one email address
        if isinstance(self.data.to_email, (list, tuple)):
            to_email = "{0} ".format(MULTI_EMAIL_FIELD_VALUE_SPLITTER).join(
                self.data.to_email
            )
        else:
            # Assume that it's string
            to_email = self.data.to_email

        context = {
            "to_name": safe_text(self.data.to_name),
            "to_email": to_email,
            "subject": safe_text(self.data.subject),
        }
        return render_to_string("mail/plugin_data_repr.html", context)
