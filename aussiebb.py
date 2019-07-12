from __future__ import annotations  # Delay type hint evaluation because circular dependencies

import calendar
import re
import time
from datetime import datetime
from typing import Optional

import requests


class AussieBB:
    """
    An instance of the Aussie Broadband API.
    """

    # API library version
    version = '0.0.1'

    # Base auth URL
    auth_base_url = 'https://myaussie-auth.aussiebroadband.com.au/'

    # Base API URL
    api_base_url = 'https://myaussie-api.aussiebroadband.com.au/'

    @property
    def customer(self) -> Customer:
        """
        The Customer instance associated with the current login.
        :return: The Customer instance associated with the current login
        """
        # Check if we do not have the data or if it is stale
        if self._customer is None or time.time() - self._customer_updated > self.cache_refresh:
            self.customer = Customer.create(self)
        return self._customer

    @customer.setter
    def customer(self, value: Customer):
        self._customer = value
        self._customer_updated = time.time()

    @property
    def services(self) -> list:
        """
        An alias for AussieBB.customer.services.
        """
        return self.customer.services

    @services.setter
    def services(self, value: list):
        self.customer.services = value

    def __init__(self, cache_refresh: int = 120000):
        """
        Creates a new Aussie Broadband API instance.
        :param cache_refresh: Duration in milliseconds data requested from the API is considered current. Anything
                              accessed after this duration will trigger a new API request. Defaults to 120 seconds.
        """
        self._cookie_dict = None
        self._refresh_token = None
        self._token_expiry = None
        self.authenticated = False
        self.cache_refresh = cache_refresh

        self._customer = None
        self._customer_updated = 0

    def login(self, username: str, password: str):
        """
        Attempts to authenticate with the given username and password.
        :param username: Account username
        :param password: Account password
        """
        req = requests.post(self.auth_base_url + 'login', json={'username': username, 'password': password})

        # Make sure we have a good status code
        if req.status_code >= 400:
            raise Exception('Something went wrong with the login request')

        # Grab the JWT cookie
        if req.cookies:
            self._cookie_dict = req.cookies
        else:
            raise Exception('Could not get cookies')

        # Unpack the response JSON
        _response_json = req.json()

        # Grab the refresh token and expiry timeout
        if 'refreshToken' in _response_json and 'expiresIn' in _response_json:
            self._refresh_token = _response_json['refreshToken']
            self._token_expiry = _response_json['expiresIn']
        else:
            raise Exception('Could not get refresh token and expiry')

        # Signal that we're authenticated now
        self.authenticated = True

    def authenticated_get(self, path: str) -> requests.api:
        """
        Sends a GET request with the base API URL and given path with authentication cookies
        :param path: Path excluding base API URL
        :return: Completed request object
        :exception Tried to make a request while unauthenticated
        :exception HTTP status code of 400 or higher received
        """
        if not self.authenticated:
            raise Exception('Cannot make request while unauthenticated')

        req = requests.get(self.api_base_url + path, cookies=self._cookie_dict)

        # Make sure we have a good status code
        if req.status_code >= 400:
            raise Exception(
                'Something went wrong when requesting {}, server returned status {}'.format(self.api_base_url + path,
                                                                                            req.status_code))

        return req


class Customer:
    """
    An Aussie Broadband customer account.
    Contains everything from postal address and communication preferences to services and account permissions.
    """

    def __init__(self, customer_number: int, billing_name: str, bill_format: int, brand: str, address: str, phone: str,
                 emails: list, payment_method: str, suspended: bool, balance: float, services: list):
        """
        Creates a new Customer instance.
        :param customer_number: Customer number
        :param billing_name: Billing name
        :param bill_format: Billing format
        :param brand: Brand service is sold under
        :param address: Billing address
        :param phone: Contact phone number
        :param emails: Contact emails
        :param payment_method: Payment method
        :param suspended: Whether the account is suspended
        :param balance: Account balance in dollars
        :param services: List of services under this account
        """
        self.customer_number = customer_number
        self.billing_name = billing_name
        self.bill_format = bill_format
        self.brand = brand
        self.address = address
        self.phone = phone
        self.emails = emails
        self.payment_method = payment_method
        self.suspended = suspended
        self.balance = balance
        self.services = services

    @staticmethod
    def create(abb_api: AussieBB) -> Customer:
        """
        Creates a new Customer instance containing the customer information associated with the given API instance.
        :type abb_api: AussieBB API instance
        :return: New Customer for the given API instance
        """

        # Have the base API make the request on our behalf
        req = abb_api.authenticated_get('customer')

        # Unpack the response JSON
        json = req.json()

        # Ok, gonna look a little messy in here, but it's just unpacking and parsing various bits and pieces starting
        # with the inner-most objects since they're dependent on everything else.

        # We'll start by iterating over each service
        services = []
        for service in json['services']['NBN']:  # I only have NBN, if you have something else please get in touch.
            try:
                # Try to populate the connection details for this service
                try:
                    connection_details = NBNDetails(
                        service['nbnDetails']['product'],
                        service['nbnDetails']['poiName'],
                        service['nbnDetails']['cvcGraph'],
                        service['nbnDetails']['speedPotential']['downloadMbps'],
                        service['nbnDetails']['speedPotential']['uploadMbps'],
                        datetime.strptime(service['nbnDetails']['speedPotential']['lastTested'], '%Y-%m-%dT%H:%M:%SZ')
                    )
                except Exception:
                    raise Exception('Failed to populate ' + type(NBNDetails).__name__)

                # Format this service's address
                address = '{} {} {}, {} {} {}'.format(
                    service['address']['streetnumber'],
                    service['address']['streetname'],
                    service['address']['streettype'],
                    service['address']['locality'],
                    service['address']['state'],
                    service['address']['postcode']
                )

                # Prepend the unit type and number if there is one
                if service['address']['subaddresstype'] and service['address']['subaddressnumber']:
                    address = '{} {}, {}'.format(service['address']['subaddresstype'], service['address']['subaddressnumber'], address)

                # Create a new NBNService instance and add it to the list
                services.append(
                    NBNService(
                        abb_api,
                        service['service_id'],
                        service['plan'],
                        service['description'],
                        connection_details,
                        datetime.strptime(service['nextBillDate'], '%Y-%m-%dT%H:%M:%SZ'),
                        datetime.strptime(service['openDate'], '%Y-%m-%d'),
                        service['usageAnniversary'],
                        service['ipAddresses'],
                        address
                    )
                )
            except Exception:
                raise Exception('Failed to populate ' + type(NBNService).__name__)

        # Then we will parse the remaining fields and plug everything into a new Customer instance
        try:
            # Format the address
            address = '{}, {} {} {}'.format(
                json['postalAddress']['address'],
                json['postalAddress']['town'],
                json['postalAddress']['state'],
                json['postalAddress']['postcode']
            )

            return Customer(
                json['customer_number'],
                json['billing_name'],
                json['billformat'],
                json['brand'],
                address,
                json['phone'],
                json['email'],
                json['payment_method'],
                json['isSuspended'],
                json['accountBalanceCents'] / 100,
                services
            )
        except Exception:
            raise Exception('Failed to populate ' + type(Customer).__name__)


class NBNService:
    """
    An NBN Internet service.
    Everything you need to know about an NBN service can be found in here.
    """
    type = 'NBN'
    name = 'NBN'
    contract = None  # <-- What is this?

    @property
    def usage_overview(self) -> OverviewServiceUsage:
        """
        The usage overview for the current month.
        :return: Usage overview for the current month
        """
        # Check if we do not have the data or if it is stale
        if not self._usage_overview or time.time() - self._usage_overview_updated > self._abb_api.cache_refresh:
            self.usage_overview = OverviewServiceUsage.create(self._abb_api, self)
        return self._usage_overview

    @usage_overview.setter
    def usage_overview(self, value: OverviewServiceUsage):
        self._usage_overview = value
        self._usage_overview_updated = time.time()

    @property
    def historic_usage(self) -> HistoricUsageDict:
        """
        Usage history.
        :return: Usage history
        """
        # Check if we do not have the data or it is stale
        if not self._historic_usage or time.time() - self._historic_usage_updated > self._abb_api.cache_refresh:
            self.historic_usage = HistoricUsageDict(self._abb_api, self)
        return self._historic_usage

    @historic_usage.setter
    def historic_usage(self, value: HistoricUsageDict):
        self._historic_usage = value
        self._historic_usage_updated = time.time()

    def __init__(self, abb_api: AussieBB, service_id: NBNService, plan: str, description: str,
                 connection_details: NBNDetails, next_bill: datetime, open_date: datetime, rollover_day: int,
                 ip_addresses: list, address: str) -> historic_usage:
        """
        Creates a new NBNService instance with the given details.
        :param abb_api: AussieBB API instance
        :param service_id: Service ID
        :param plan: Plan description
        :param description: Service description (usually an address)
        :param connection_details: NBNDetails instance for this service
        :param next_bill: Next bill date
        :param open_date: Date the service was opened
        :param rollover_day: Day of each month that usage rolls over
        :param ip_addresses: IP addresses allocated to this service
        :param address: Physical address of this service
        """
        self._abb_api = abb_api
        self.service_id = service_id
        self.plan = plan
        self.description = description
        self.connection_details = connection_details
        self.next_bill = next_bill
        self.open_date = open_date
        self.rollover_day = rollover_day
        self.ip_addresses = ip_addresses
        self.address = address

        self._usage_overview = None
        self._usage_overview_updated = 0

        self._historic_usage = None
        self._historic_usage_updated = 0


class OverviewServiceUsage:
    """
    Overview usage data for the current month.
    Usage is in megabytes (10^6 bytes).
    """
    def __init__(self, total: int, download: int, upload: int, remaining: int, days_total: int, days_remaining: int,
                 last_update: datetime):
        """
        Creates a new OverviewServiceUsage instance with the given data.
        :param total: Combined upload and download usage in megabytes
        :param download: Download usage
        :param upload: Upload usage
        :param remaining: Usage remaining
        :param days_total: Days in usage period
        :param days_remaining: Days until next usage period
        :param last_update: Time data was last updated
        """
        self.total = total
        self.download = download
        self.upload = upload
        self.remaining = remaining
        self.days_total = days_total
        self.days_remaining = days_remaining
        self.last_update = last_update

    @staticmethod
    def create(abb_api: AussieBB, service: NBNService) -> OverviewServiceUsage:
        """
        Creates a new OverviewServiceUsage instance containing usage overview information associated with the given service.
        :param abb_api: AussieBB API instance
        :param service: Service to get data from
        :return: New OverviewServiceUsage for the given service
        """
        req = abb_api.authenticated_get('broadband/' + str(service.service_id) + '/usage')

        # Unpack the response JSON
        json = req.json()

        try:
            return OverviewServiceUsage(
                json['usedMb'],
                json['downloadedMb'],
                json['uploadedMb'],
                json['remainingMb'],
                json['daysTotal'],
                json['daysRemaining'],
                json['lastUpdated']
            )
        except Exception:
            raise Exception('Failed to populate ' + type(OverviewServiceUsage).__name__)


class HistoricUsageDict:
    """
    Historic usage data dictionary wrapper to handle funky dates.
    Access with YYYY-MM-DD date format. Specifying only YYYY or YYYY-MM will fill in the remaining months and days.
    """

    _key_format = '{}-{:0>2}-{:0>2}'

    _key_regex = r'^\d{4}-\d{2}-\d{2}$'

    def __init__(self, abb_api: AussieBB, service: NBNService):
        """
        Creates a new HistoricUsageDict instance for the given service.
        :param abb_api: AussieBB API instance
        :param service: Service to request history for
        """
        self._abb_api = abb_api
        self._service = service
        self._history = {}

    def __getitem__(self, key: str) -> list:
        """
        Retrieves the usage for a given day, month, or year.
        :param key: Date string formatted as YYYY-MM-DD, YYYY-MM, or YYYY
        :return: List of HistoricUsage instances within the date provided
        """
        output = []
        match = re.match(r'^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?$', key)  # 4-digit year, optional 1- or 2-digit month, optional 1- or 2-digit day
        if match:
            year = int(match.group(1))
            month = int(match.group(2)) if match.group(2) else None  # Pad month with a zero
            day = int(match.group(3)) if match.group(3) else None  # Pad day with a zero

            # Get everything from that year
            if not month:
                for month in range(1, 12):
                    for day in calendar.monthrange(year, month):
                        key = self._key_format.format(year, month, day)
                        usage = self._try_get_date(key)
                        if usage:
                            output.append(usage)

                return output

            # Get everything from that month
            if not day:
                for day in calendar.monthrange(year, month):
                    key = self._key_format.format(year, month, day)
                    usage = self._try_get_date(key)
                    if usage:
                        output.append(usage)

                return output

            # Get the specific day
            key = self._key_format.format(year, month, day)
            usage = self._try_get_date(key)
            if usage:
                # Listify to keep consistent
                return [usage]
            else:
                # Got nothing, return an empty list instead
                return []
        else:
            raise KeyError()

    def __setitem__(self, key: str, value: HistoricUsage):
        """
        Add or update an item within the dictionary.
        All keys must match a YYYY-MM-DD date format.
        :param key: Key to add or update
        :param value: Value to set
        :exception KeyError: Key format does not match YYYY-MM-DD
        """
        if re.match(self._key_regex, key):
            self._history[key] = value
        else:
            raise KeyError()

    def _try_get_date(self, key: str) -> Optional[HistoricUsage]:
        """
        Tries to get usage data for the given date, querying the API if a cached version is not available.
        :param key: Date formatted as YYYY-MM-DD
        :return: HistoricUsage instance or None if no result
        """
        if key in self._history:
            return self._history[key]
        else:
            match = re.match(r'^(\d{4})-(\d{2})-(\d{2})$', key)
            year = int(match.group(1))
            month = int(match.group(2))
            day = int(match.group(3))

            # The API handles months as the month the usage period started in, so if a period starts on the 28th of June
            # it will provide the 28th-30th of June and the 1st-27th of July. To get around this, we'll check if the day
            # comes before the rollover. If it does, we'll make a request for the previous month.
            if day < self._service.rollover_day:
                if month > 1:
                    month -= 1
                else:
                    year -= 1
                    month = 12

            # Format the endpoint to the actual month the API is expecting for this date
            endpoint = 'broadband/{}/usage/{}/{}'.format(str(self._service.service_id), year, month)
            req = self._abb_api.authenticated_get(endpoint)

            json = req.json()

            # Cache all dates within the response
            for date in json['data']:
                self._history[date['date']] = HistoricUsage(date['date'], date['download'], date['upload'])

            # Check if we have the entry now
            if key in self._history:
                # Return it
                return self._history[key]
            else:
                # The entry still isn't here, so return nothing
                return None


class HistoricUsage:
    """
    Historic usage data.
    Usage is in megabytes (10^6 bytes)
    """

    def __init__(self, date: datetime, download: int = 0, upload: int = 0):
        """
        Creates a new HistoricUsage instance.
        :param date: Date the usage data is for
        :param download: Download usage in megabytes
        :param upload: Upload usage in megabytes
        """
        self.date = date
        self.download = download
        self.upload = upload


class NBNDetails:
    """
    Line details for an NBN service.
    Describes the connection type, POI, and speed potential.
    """
    def __init__(self, connection_type: str, poi: str, cvc_graph_url: str, download_potential: int,
                 upload_potential: int, last_test: datetime):
        """
        Creates a new NBNDetails instance.
        :param connection_type: Physical connection technology type
        :param poi: Name of the Point-Of-Interconnect that the service is connected to
        :param cvc_graph_url: URL for the CVC graph image
        :param download_potential: Potential download speed in megabits-per-second
        :param upload_potential: Potential upload speed in megabits-per-second
        :param last_test: Date and time the connection speeds were last updated
        """
        self.connection_type = connection_type
        self.poi = poi
        self.cvc_graph_url = cvc_graph_url
        self.download_potential = download_potential
        self.upload_potential = upload_potential
        self.last_test = last_test
