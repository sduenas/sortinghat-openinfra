# -*- coding: utf-8 -*-
#
# Copyright (C) 2023 Bitergia
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#
# Authors:
#     Jose Javier Merchante <jjmerchante@bitergia.com>
#

import datetime
import logging

import dateutil.tz
import requests

from grimoirelab_toolkit.datetime import str_to_datetime
from grimoirelab_toolkit.uris import urijoin
from sortinghat.core.errors import LoadError
from sortinghat.core.importer.backend import IdentitiesImporter
from sortinghat.core.importer.models import (Individual,
                                             Identity,
                                             Enrollment,
                                             Organization,
                                             Profile)

logger = logging.getLogger(__name__)


class OpenInfraIDImporter(IdentitiesImporter):

    NAME = 'OpenInfraID'

    def __init__(self, ctx, url, from_date=None):
        super().__init__(ctx, url)
        if isinstance(from_date, str):
            from_date = str_to_datetime(from_date)
        self.from_date = from_date

    def get_individuals(self):
        parser = OpenInfraIDParser(self.url)
        return parser.individuals(self.from_date)


class OpenInfraIDParser:
    """Parse identities and organizations from OpenInfraID API.

    The OpenInfraID data is from and API that provides the
    identities and organizations of all the individuals.

    The individuals are stored in an object named 'individuals'.
    The keys of this object are the UUID of the individuals.
    Each individual object stores a list of identities and
    enrollments.

    :param url: OpenInfraID API URL
    :param last_update: datetime of the last update in UTC format

    :raises InvalidFormatError: raised when the format of the stream is
        not valid.
    """

    # API path
    MEMBERS = '/api/public/v1/members'

    # Resource parameters
    PPER_PAGE = 'per_page'
    PPAGE = 'page'
    PSORT = 'sort'
    PFILTER = 'filter'

    def __init__(self, url):
        self.url = url
        self.source = 'openinfra'

    def individuals(self, from_date=None):
        """Fetch individuals from the OpenInfraID API

        This method returns an iterator of individuals. Each
        individual can contain an OpenInfraID identity which
        username is the ID of the member, a GitHub identity,
        and the enrollment of that identity.

        The OpenInfraID members that don't contain any information
        like name, GitHub identity or enrollments are skipped.

        :param from_date: obtain members updated since this date

        :returns: a generator of individuals
        """

        for member in self.fetch_members(from_date):
            uuid = member.get('id')
            name = f"{member.get('first_name', '')} {member.get('last_name', '')}".strip()
            github_user = member.get('github_user')
            affiliations = member.get('affiliations', [])
            if not name and not github_user:
                # Skip individuals that can't be identified in SH
                logger.warning("Skip empty individual")
                continue
            individual = Individual(uuid=uuid)
            prf = Profile()
            individual.profile = prf
            if name:
                idt = Identity(source=self.source, name=name, username=str(uuid))
                individual.identities.append(idt)
                prf.name = name
            if github_user:
                idt = Identity(source='github', name=name, username=github_user)
                individual.identities.append(idt)

            for aff in affiliations:
                org = Organization(name=aff['organization']['name'])
                start, end = None, None
                if aff['start_date']:
                    start = datetime.datetime.fromtimestamp(aff['start_date'],
                                                            tz=dateutil.tz.tzutc())
                if aff['end_date']:
                    end = datetime.datetime.fromtimestamp(aff['end_date'],
                                                          tz=dateutil.tz.tzutc())
                enr = Enrollment(org, start=start, end=end)
                individual.enrollments.append(enr)

            yield individual

    def fetch_members(self, from_date=None):
        """Fetch the members from the repository.

        The method retrieves, from an OpenInfraID API, the members
        updated since the given date.

        :param from_date: obtain members updated since this date

        :returns: a generator of members
        """
        payload = {
            self.PPER_PAGE: 100,
            self.PSORT: '-last_edited',
            self.PPAGE: 1,
        }

        if from_date:
            payload[self.PFILTER] = 'last_edited>' + str(int(from_date.timestamp()))

        url = urijoin(self.url, self.MEMBERS)

        raw_members = self.fetch_items(url, payload)
        for members in raw_members:
            for member in members['data']:
                yield member

    @staticmethod
    def fetch_items(url, payload=None):
        """Return items using pagination"""

        if not payload:
            payload = {}

        page = 1
        while True:
            response = requests.get(url, params=payload)
            if not response.ok:
                raise LoadError(cause=f"Error fetching items. Status code <{response.status_code}>")

            data = response.json()
            yield data

            if page >= data['last_page']:
                break
            page += 1
            payload['page'] = page
