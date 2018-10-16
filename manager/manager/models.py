#!/usr/bin/env python
# -*- coding: utf-8 -*-
# vim: ai ts=4 sts=4 et sw=4 nu

import json
import logging
import collections
from pathlib import Path

import pytz
import pycountry
import jsonfield
import phonenumbers
from django.db import models
from django.conf import settings
from django.contrib.auth.models import User

from manager.pibox.packages import get_packages_id
from manager.pibox.data import ideascube_languages
from manager.pibox.util import ONE_GB, b64encode, b64decode, human_readable_size
from manager.pibox.config import (
    get_uuid,
    get_if_str,
    get_if_str_in,
    get_nested_key,
    extract_branding,
    get_list_if_values_match,
)
from manager.pibox.content import get_collection, get_required_image_size

logger = logging.getLogger(__name__)


def get_channel_choices():
    from manager.scheduler import get_channels_list, as_items_or_none

    channels = as_items_or_none(*get_channels_list())
    if channels is None:
        return [("kiwix", "Kiwix")]
    return [
        (
            channel.get("slug"),
            "{name} ({pub})".format(
                name=channel.get("name"),
                pub="Private" if channel.get("private") else "Public",
            ),
        )
        for channel in channels
        if channel.get("active", False)
    ]


def get_branding_path(instance, filename):
    return "{uuid}_{fname}".format(uuid=get_uuid(), fname=filename)


def save_branding_file(branding_file):
    rpath = get_branding_path(1, branding_file.get("fname"))
    b64decode(rpath, branding_file.get("data"), settings.MEDIA_ROOT)
    return rpath


def retrieve_branding_file(field):
    fpath = Path(settings.MEDIA_ROOT).joinpath(field.name)
    fname = Path(field.name).name.split("_")[-1]  # remove UUID
    return {"fname": fname, "data": b64encode(fpath)}


class Configuration(models.Model):
    class Meta:
        get_latest_by = "-id"
        ordering = ["-id"]

    KALITE_LANGUAGES = ["en", "fr", "es"]
    WIKIFUNDI_LANGUAGES = ["en", "fr"]

    organization = models.ForeignKey(
        "Organization", on_delete=models.CASCADE, related_name="configurations"
    )
    updated_on = models.DateTimeField(auto_now=True)

    name = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Used <strong>only within the Cardshop</strong>",
    )
    project_name = models.CharField(
        max_length=100,
        default="Kiwix Hotspot",
        help_text="Used to name your Box and its WiFi",
    )
    language = models.CharField(
        max_length=3, choices=ideascube_languages.items(), default="en"
    )
    timezone = models.CharField(
        max_length=50,
        choices=[(tz, tz) for tz in pytz.common_timezones],
        default="Europe/Paris",
    )

    wifi_password = models.CharField(
        max_length=100,
        default=None,
        verbose_name="WiFi Password",
        help_text="Leave Empty for Open WiFi",
        null=True,
        blank=True,
    )
    admin_account = models.CharField(max_length=50, default="admin")
    admin_password = models.CharField(
        max_length=50,
        default="admin-password",
        help_text="To manage Ideascube, KA-Lite, Aflatoun, EduPi and Wikifundi",
    )

    branding_logo = models.FileField(
        blank=True, null=True, upload_to=get_branding_path, verbose_name="Logo"
    )
    branding_favicon = models.FileField(
        blank=True, null=True, upload_to=get_branding_path, verbose_name="Favicon"
    )
    branding_css = models.FileField(
        blank=True, null=True, upload_to=get_branding_path, verbose_name="CSS File"
    )

    content_zims = jsonfield.JSONField(
        blank=True,
        null=True,
        load_kwargs={"object_pairs_hook": collections.OrderedDict},
        default="",
    )
    content_kalite_fr = models.BooleanField(
        default=False,
        verbose_name="Khan Academy FR",
        help_text="Learning Platform (French)",
    )
    content_kalite_en = models.BooleanField(
        default=False,
        verbose_name="Khan Academy EN",
        help_text="Learning Platform (English)",
    )
    content_kalite_es = models.BooleanField(
        default=False,
        verbose_name="Khan Academy ES",
        help_text="Learning Platform (Spanish)",
    )
    content_wikifundi_fr = models.BooleanField(
        default=False,
        verbose_name="WikiFundi FR",
        help_text="Wikipedia-like Editing Platform (French)",
    )
    content_wikifundi_en = models.BooleanField(
        default=False,
        verbose_name="WikiFundi EN",
        help_text="Wikipedia-like Editing Platform (English)",
    )
    content_aflatoun = models.BooleanField(
        default=False, verbose_name="Aflatoun", help_text="Education Platform for kids"
    )
    content_edupi = models.BooleanField(
        default=False,
        verbose_name="EduPi",
        help_text="Share arbitrary files with all users",
    )
    content_edupi_resources = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        verbose_name="EduPi Resources",
        help_text="ZIP folder archive of documents to initialize EduPi with",
    )

    @classmethod
    def create_from(cls, config, organization):

        # only packages IDs which are in the catalogs
        packages_list = get_list_if_values_match(
            get_nested_key(config, ["content", "zims"]), get_packages_id()
        )
        # list of requested langs for kalite
        kalite_langs = get_list_if_values_match(
            get_nested_key(config, ["content", "kalite"]), cls.KALITE_LANGUAGES
        )
        # list of requested langs for wikifundi
        wikifundi_langs = get_list_if_values_match(
            get_nested_key(config, ["content", "wikifundi"]), cls.WIKIFUNDI_LANGUAGES
        )

        # branding
        logo = extract_branding(config, "logo", ["image/png"])
        favicon = extract_branding(config, "favicon", ["image/x-icon", "image/png"])
        css = extract_branding(config, "css", ["text/css", "text/plain"])

        # WiFi used to have 2 keys (protected and password)
        wifi_protected = bool(get_nested_key(config, ["wifi", "protected"]))

        # rebuild clean config from data
        kwargs = {
            "organization": organization,
            "project_name": get_if_str(get_nested_key(config, "project_name")),
            "language": get_if_str_in(
                get_nested_key(config, "language"),
                dict(cls._meta.get_field("language").choices).keys(),
            ),
            "timezone": get_if_str_in(
                get_nested_key(config, "timezone"),
                dict(cls._meta.get_field("timezone").choices).keys(),
            ),
            "wifi_password": get_if_str(get_nested_key(config, ["wifi", "password"]))
            if wifi_protected
            else None,
            "admin_account": get_if_str(
                get_nested_key(config, ["admin_account", "login"])
            ),
            "admin_password": get_if_str(
                get_nested_key(config, ["admin_account", "password"])
            ),
            "branding_logo": save_branding_file(logo) if logo is not None else None,
            "branding_favicon": save_branding_file(favicon)
            if favicon is not None
            else None,
            "branding_css": save_branding_file(css) if css is not None else None,
            "content_zims": packages_list,
            "content_kalite_fr": "fr" in kalite_langs,
            "content_kalite_en": "en" in kalite_langs,
            "content_kalite_es": "es" in kalite_langs,
            "content_wikifundi_fr": "fr" in wikifundi_langs,
            "content_wikifundi_en": "en" in wikifundi_langs,
            "content_aflatoun": bool(get_nested_key(config, ["content", "aflatoun"])),
            "content_edupi": bool(get_nested_key(config, ["content", "edupi"])),
            "content_edupi_resources": get_if_str(
                get_nested_key(config, ["content", "edupi_resources"])
            ),
        }

        try:
            return cls.objects.create(**kwargs)
        except Exception as exp:
            logger.warn(exp)

            # remove saved branding files
            for key in ("branding_logo", "branding_favicon", "branding_css"):
                if kwargs.get(key):
                    try:
                        Path(settings.MEDIA_ROOT).joinpath(kwargs.get(key))
                    except FileNotFoundError:
                        pass
            raise exp

    @classmethod
    def get_choices(cls, organization):
        return [
            (item.id, item.name)
            for item in cls.objects.filter(organization=organization)
        ]

    @classmethod
    def get_or_none(cls, id):
        try:
            return cls.objects.get(id=id)
        except cls.DoesNotExist:
            return None

    @property
    def wifi_protected(self):
        return bool(self.wifi_password)

    @property
    def display_name(self):
        return self.name or self.project_name

    @property
    def json(self):
        return json.dumps(self.to_dict(), indent=4)

    @property
    def min_media(self):
        return Media.get_min_for(self.size)

    @property
    def min_units(self):
        return self.min_media.units

    @property
    def kalite_languages(self):
        return [
            lang
            for lang in self.KALITE_LANGUAGES
            if getattr(self, "content_kalite_{}".format(lang), False)
        ]

    @property
    def wikifundi_languages(self):
        return [
            lang
            for lang in self.KALITE_LANGUAGES
            if getattr(self, "content_wikifundi_{}".format(lang), False)
        ]

    def all_languages(self):
        return self._meta.get_field("language").choices

    def __str__(self):
        return self.display_name

    @property
    def collection(self):
        return get_collection(
            edupi=self.content_edupi,
            edupi_resources=self.content_edupi_resources or None,
            packages=self.content_zims or [],
            kalite_languages=self.kalite_languages,
            wikifundi_languages=self.wikifundi_languages,
            aflatoun_languages=["fr", "en"] if self.content_aflatoun else [],
        )

    @property
    def size(self):
        return get_required_image_size(self.collection)

    def to_dict(self):
        # for key in ("project_name", "language", "timezone"):
        #     config.append((key, getattr(self, key)))
        return collections.OrderedDict(
            [
                ("project_name", self.project_name),
                ("language", self.language),
                ("timezone", self.timezone),
                ("wifi_password", self.wifi_password),
                (
                    "admin_account",
                    collections.OrderedDict(
                        [
                            ("login", self.admin_account),
                            ("password", self.admin_password),
                        ]
                    ),
                ),
                ("size", self.min_media.human),
                (
                    "content",
                    collections.OrderedDict(
                        [
                            ("zims", self.content_zims),
                            ("kalite", self.kalite_languages),
                            ("wikifundi", self.wikifundi_languages),
                            ("aflatoun", self.content_aflatoun),
                            ("edupi", self.content_edupi),
                            ("edupi_resources", self.content_edupi_resources),
                        ]
                    ),
                ),
                (
                    "branding",
                    collections.OrderedDict(
                        [
                            ("logo", retrieve_branding_file(self.branding_logo)),
                            ("favicon", retrieve_branding_file(self.branding_favicon)),
                            ("css", retrieve_branding_file(self.branding_css)),
                        ]
                    ),
                ),
            ]
        )


class Organization(models.Model):
    class Meta:
        ordering = ["slug"]

    slug = models.SlugField(primary_key=True)
    name = models.CharField(max_length=100)
    channel = models.CharField(
        max_length=50, choices=get_channel_choices(), default="kiwix"
    )
    email = models.EmailField()
    units = models.IntegerField()

    @classmethod
    def get_or_none(cls, slug):
        try:
            return cls.objects.get(slug=slug)
        except cls.DoesNotExist:
            return None

    @classmethod
    def create_kiwix(cls):
        if cls.objects.filter(slug="kiwix").count():
            return cls.objects.get(slug="kiwix")
        return cls.objects.create(
            slug="kiwix", name="Kiwix", email="reg@kiwix.org", units=100000
        )

    def __str__(self):
        return self.name


class Profile(models.Model):
    class Meta:
        ordering = ["organization", "user__username"]

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)

    @property
    def username(self):
        return self.user.username

    @property
    def email(self):
        return self.user.email

    @classmethod
    def get_or_none(cls, username):
        try:
            return cls.objects.get(user__username=username)
        except (cls.DoesNotExist, User.DoesNotExist):
            return None

    @classmethod
    def create_admin(cls):
        organization = Organization.create_kiwix()

        if User.objects.filter(username="admin").count():
            user = User.objects.get(username="admin")
        else:
            user = User.objects.create_superuser(
                username="admin",
                email=organization.email,
                password=settings.ADMIN_PASSWORD,
            )
        if cls.objects.filter(user=user).count():
            return cls.objects.get(user=user)

        return cls.objects.create(user=user, organization=organization)

    @classmethod
    def exists(cls, username):
        return bool(User.objects.filter(username=username).count())

    @classmethod
    def taken(cls, email):
        return bool(User.objects.filter(email=email).count())

    @classmethod
    def create(cls, organization, first_name, email, username, password, is_admin):
        if cls.exists(username) or cls.taken(email):
            raise ValueError("Profile parameters non unique")

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            is_staff=is_admin,
            is_superuser=is_admin,
        )

        try:
            return cls.objects.create(user=user, organization=organization)
        except Exception as exp:
            logger.error(exp)
            # make sure we remove the User object so it can be recreated later
            user.delete()
            raise exp

    @property
    def name(self):
        return self.user.get_full_name()

    def __str__(self):
        return "{user} ({org})".format(user=self.name, org=str(self.organization))


class Address(models.Model):

    COUNTRIES = collections.OrderedDict(
        sorted([(c.alpha_2, c.name) for c in pycountry.countries], key=lambda x: x[1])
    )

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    name = models.CharField(max_length=100, verbose_name="Address Name")
    recipient = models.CharField(max_length=100)
    email = models.CharField(max_length=255, blank=True, null=True)
    phone = models.CharField(max_length=30)
    address = models.TextField()
    country = models.CharField(max_length=50, choices=COUNTRIES.items())

    @classmethod
    def get_or_none(cls, aid):
        try:
            return cls.objects.get(id=aid)
        except cls.DoesNotExist:
            return None

    def save(self, *args, **kwargs):
        self.phone = self.cleaned_phone(self.phone)
        super().save(*args, **kwargs)

    @classmethod
    def get_choices(cls, organization):
        return [
            (item.id, item.name)
            for item in cls.objects.filter(organization=organization)
        ]

    @property
    def verbose_country(self):
        return self.COUNTRIES.get(self.country)

    @property
    def human_phone(self):
        return phonenumbers.format_number(
            phonenumbers.parse(self.phone, None),
            phonenumbers.PhoneNumberFormat.INTERNATIONAL,
        )

    @staticmethod
    def cleaned_phone(number):
        pn = phonenumbers.parse(number, None)
        if not phonenumbers.is_possible_number(pn):
            raise ValueError("Phone Number not possible")
        return phonenumbers.format_number(pn, phonenumbers.PhoneNumberFormat.E164)

    def to_payload(self):
        return {
            "name": self.recipient,
            "email": self.email,
            "phone": self.human_phone,
            "address": self.address,
            "country": self.country,
            "shipment": None,
        }

    def __str__(self):
        return self.name


class Media(models.Model):

    REGULAR = "regular"
    KINDS = {REGULAR: "Regular"}

    class Meta:
        unique_together = (("kind", "size"),)
        ordering = ["size"]

    name = models.CharField(max_length=50)
    kind = models.CharField(max_length=50, choices=KINDS.items())
    size = models.IntegerField(help_text="In GB")
    units_coef = models.FloatField(
        verbose_name="Units", help_text="How much units per GB"
    )

    @classmethod
    def get_or_none(cls, mid):
        try:
            return cls.objects.get(id=mid)
        except cls.DoesNotExist:
            return None

    @classmethod
    def get_choices(cls):
        return [(item.id, item.name) for item in cls.objects.all()]

    @classmethod
    def get_min_for(cls, size):
        try:
            return cls.objects.filter(size__gte=size // ONE_GB).order_by("size").first()
        except cls.DoesNotExist:
            return None

    def __str__(self):
        return self.name

    @property
    def bytes(self):
        return self.size * ONE_GB

    @property
    def human(self):
        return human_readable_size(self.bytes, False)

    @property
    def units(self):
        return self.size * self.units_coef

    @property
    def verbose_kind(self):
        return self.KINDS.get(self.kind)


class Order(models.Model):
    IN_PROGRESS = "in-progress"
    FAILED = "failed"
    COMPLETED = "completed"

    STATUSES = {IN_PROGRESS: "In Progress", COMPLETED: "Completed", FAILED: "Failed"}

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    scheduler_id = models.UUIDField(unique=True, blank=True)
    created_on = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(Profile, on_delete=models.CASCADE)
    status = models.CharField(
        max_length=50, choices=STATUSES.items(), default=IN_PROGRESS
    )

    @property
    def active(self):
        return self.status == self.IN_PROGRESS

    @property
    def short_id(self):
        return self.scheduler_id[:8] + self.scheduler_id[-3:]

    def __str__(self):
        return "Order #{id}".format(self.id)


# class OrderItem(models.Model):
#     order = models.ForeignKey(Order, on_delete=models.CASCADE)
#     configuration = models.ForeignKey(Configuration, on_delete=models.PROTECT)
#     media = models.ForeignKey(Media, on_delete=models.PROTECT)
#     quantity = models.IntegerField()

#     def __str__(self):
#         return "OrderItem #{id} (Order #{order})".format(
#             id=self.id, order=self.order.id
#         )

#     @property
#     def units(self):
#         return self.media.units * self.quantity
