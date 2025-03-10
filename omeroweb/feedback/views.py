#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#
#
# Copyright (c) 2008 University of Dundee.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# Author: Aleksandra Tarkowska <A(dot)Tarkowska(at)dundee(dot)ac(dot)uk>, 2008.
#
# Version: 1.0
#

"""A view functions is simply a Python function that takes a Web request and
returns a Web response. This response can be the HTML contents of a Web page,
or a redirect, or the 404 and 500 error, or an XML document, or an image...
or anything."""

import sys
import datetime
import traceback
import logging

from django.conf import settings
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.http import HttpResponseServerError, HttpResponseNotFound
from django.views.defaults import page_not_found
from django.urls import reverse
from django.shortcuts import render

from django.views.debug import get_exception_reporter_filter
from django.utils.encoding import force_str

from omeroweb.connector import Connector, Server
from omeroweb.feedback.sendfeedback import SendFeedback
from omeroweb.feedback.forms import ErrorForm, CommentForm
from omeroweb.utils import is_ajax
from omeroweb.version import omeroweb_version

logger = logging.getLogger(__name__)


def get_user_agent(request):
    user_agent = ""
    try:
        user_agent = request.META["HTTP_USER_AGENT"]
    except Exception:
        pass
    return user_agent


###############################################################################
def send_feedback(request):
    if not settings.FEEDBACK_ERROR_ENABLED:
        return HttpResponseRedirect(reverse("feedback_disabled"))

    error = None
    form = ErrorForm(data=request.POST.copy())
    if form.is_valid():
        error = form.cleaned_data["error"]
        comment = form.cleaned_data["comment"]
        email = form.cleaned_data["email"]
        try:
            sf = SendFeedback(settings.FEEDBACK_URL)
            sf.send_feedback(
                error=error,
                comment=comment,
                email=email,
                user_agent=get_user_agent(request),
            )
        except Exception as e:
            logger.error("handler500: Feedback could not be sent")
            logger.error(traceback.format_exc())
            error = (
                "Feedback could not be sent. Please contact" " administrator. %s" % e
            )
            fileObj = open(
                ("%s/error500-%s.html" % (settings.LOGDIR, datetime.datetime.now())),
                "w",
            )
            try:
                try:
                    fileObj.write(request.POST["error"])
                except Exception:
                    logger.error("handler500: Error could not be saved.")
                    logger.error(traceback.format_exc())
            finally:
                fileObj.close()
        else:
            if is_ajax(request):
                return HttpResponse(
                    "<h1>Thanks for your feedback</h1><p>You may need to"
                    " refresh your browser to recover from the error</p>"
                )
            return HttpResponseRedirect(reverse("fthanks"))

    context = {"form": form, "error": error}
    return render(request, "500.html", context)


def send_comment(request):
    if not settings.FEEDBACK_COMMENT_ENABLED:
        return HttpResponseRedirect(reverse("feedback_disabled"))

    error = None
    form = CommentForm()

    if request.method == "POST":
        form = CommentForm(data=request.POST.copy())
        if form.is_valid():
            comment = form.cleaned_data["comment"]
            email = form.cleaned_data["email"]
            try:
                sf = SendFeedback(settings.FEEDBACK_URL)
                sf.send_feedback(
                    comment=comment, email=email, user_agent=get_user_agent(request)
                )
            except Exception:
                logger.error("handler500: Feedback could not be sent")
                logger.error(traceback.format_exc())
                error = "Feedback could not be sent." " Please contact administrator."
            else:
                return HttpResponseRedirect(reverse("fthanks"))

    versions = list()
    for server in Server.find():
        bioformats_version = "Unknown"
        conn = Connector(server.id, True).create_guest_connection("OMERO.web")
        try:

            def get_config_value(key):
                try:
                    return conn.getConfigService().getConfigValue(key)
                except Exception:
                    logger.warn("Could not get config value: %s" % key)
                return "Unknown"

            bioformats_version = get_config_value("omero.bioformats.version")
            omero_version = get_config_value("omero.version")
        finally:
            if conn is not None:
                conn.close()
        versions.append(
            {
                "server": server.server,
                "bioformats_version": bioformats_version,
                "omero_version": omero_version,
                "omeroweb_version": omeroweb_version,
            }
        )
    context = {
        "form": form,
        "error": error,
        "versions": versions,
    }
    return render(request, "comment.html", context)


##############################################################################
# handlers


def csrf_failure(request, reason=""):
    """
    Always return Json response
    since this is accepted by browser and API users
    """
    return JsonResponse({"message": f"CSRF Failed: {reason}"}, status=403)


def handler500(request):
    """
    Custom error handling.
    Catches errors that are not handled elsewhere.
    NB: This only gets used by Django if omero.web.debug False (production use)
    If debug is True, Django returns it's own debug error page
    """
    logger.error("handler500: Server error")

    as_string = "\n".join(traceback.format_exception(*sys.exc_info()))
    logger.error(as_string)

    try:
        error_filter = get_exception_reporter_filter(request)
        try:
            request_repr = "\n{}".format(
                force_str(error_filter.get_request_repr(request))
            )
        except Exception:
            request_repr = error_filter.get_request_repr(request)
    except Exception:
        try:
            request_repr = repr(request)
        except Exception:
            request_repr = "Request unavailable"

    error500 = "%s\n%s" % (as_string, request_repr)

    # If AJAX, return JUST the error message (not within html page)
    if is_ajax(request):
        return HttpResponseServerError(error500)

    if settings.FEEDBACK_ERROR_ENABLED:
        form = ErrorForm(initial={"error": error500})
        context = {"form": form}
        template = "500.html"
    else:
        context = {"error500": error500}
        template = "500-nosubmit.html"
    return render(request, template, context, status=500)


def handler404(request, exception=None):
    logger.warning(
        "Not Found: %s" % request.path, extra={"status_code": 404, "request": request}
    )
    if is_ajax(request):
        return HttpResponseNotFound()

    return page_not_found(request, "404.html")


def handlerInternalError(request, error):
    """
    This is mostly used in an "object not found" situation,
    So there is no feedback form - simply display "not found" message.
    If the call was AJAX, we return the message in a 404 response.
    Otherwise return an html page, with 404 response.
    """
    logger.warning(
        "Object Not Found: %s" % request.path,
        extra={"status_code": 404, "request": request},
    )

    if is_ajax(request):
        return HttpResponseNotFound(error)

    context = {"error": error}
    return render(request, "error.html", context, status=404)
