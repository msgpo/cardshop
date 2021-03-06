#!/usr/bin/env python
# -*- coding: utf-8 -*-
# vim: ai ts=4 sts=4 et sw=4 nu

import json
import base64
from pathlib import Path

import humanfriendly
import dateutil.parser
from django import template

from manager.models import Address, Order
from manager.pibox.util import human_readable_size
from manager.pibox.packages import get_parsed_package, get_package

register = template.Library()


def human_size(value, binary=True):
    return human_readable_size(value, binary).replace(" ", " ")


register.filter("human_size", human_size)


def human_number(value, decimals=0):
    return humanfriendly.format_number(value, num_decimals=decimals)


register.filter("human_number", human_number)


def parsed_sname(package):
    return get_parsed_package(package)["sname"]


register.filter("parsed_sname", parsed_sname)


def decodeb64(value):
    return base64.b64decode(value).decode("UTF-8")


register.filter("decodeb64", decodeb64)


def fname(value):
    return Path(value).name.split("_")[-1]


register.filter("fname", fname)


def as_packages(value):
    return [get_package(pid) for pid in json.loads(value) or []]


register.filter("as_packages", as_packages)


def as_widget(field):
    if not hasattr(field, "as_widget"):
        return field
    our_classes = ["form-control"]
    if getattr(field, "errors", False):
        our_classes += ["alert-danger"]
    return field.as_widget(attrs={"class": field.css_classes(" ".join(our_classes))})


register.filter("as_widget", as_widget)


def country_name(country_code):
    return Address.country_name_for(country_code)


register.filter("country", country_name)


def get_id(mongo_data):
    return mongo_data.get("_id") if isinstance(mongo_data, dict) else None


register.filter("id", get_id)


def clean_statuses(items):
    if not isinstance(items, list):
        return []
    return sorted(
        [
            {
                "status": item.get("status"),
                "on": dateutil.parser.parse(item.get("on")),
                "payload": item.get("payload"),
            }
            for item in items
        ],
        key=lambda x: x["on"],
        reverse=True,
    )


register.filter("clean_statuses", clean_statuses)


def plus_one(number):
    return number + 1


register.filter("plus_one", plus_one)


def status_color(status):
    return {
        Order.COMPLETED: "message-success",
        Order.FAILED: "message-error",
        Order.NOT_CREATED: "message-error",
    }.get(status, "")


register.filter("status_color", status_color)


def clean_datetime(dt):
    return dateutil.parser.parse(dt) if dt else None


register.filter("datetime", clean_datetime)
