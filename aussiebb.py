import re
import time
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
    def customer(self):
        # Check if we do not have the data or if it is stale
        if self._customer is None or time.time() - self._customer_updated > self.cache_refresh:
            self.customer = self._get_customer()
        return self._customer

    @customer.setter
    def customer(self, value):
        self._customer = value
        self._customer_updated = time.time()

    def __init__(self, cache_refresh=120000):
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

    def login(self, username, password):
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

    def authenticated_get(self, path):
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

    def _get_customer(self):
        """
        Gets the customer information associated with this account.
        :return: Customer information
        """

        if not self.authenticated:
            raise Exception('Cannot get customer data while unauthenticated')

        req = requests.get(self.api_base_url + 'customer', cookies=self._cookie_dict)

        # Make sure we have a good status code
        if req.status_code >= 400:
            raise Exception('Something went wrong when requesting {}, server returned status {}'.format(
                self.api_base_url + 'customer', req.status_code))

        # Unpack the response JSON
        json = req.json()

        # Try create a Customer from the response
        try:
            customer_number = json['customer_number']
            billing_name = json['billing_name']
            bill_format = json['billformat']
            brand = json['brand']
            address = '{}, {} {} {}'.format(json['postalAddress']['address'], json['postalAddress']['town'],
                                            json['postalAddress']['state'], json['postalAddress']['postcode'])
            phone = json['phone']
            emails = json['email']
            payment_method = json['payment_method']
            suspended = json['isSuspended']
            balance = json['accountBalanceCents'] / 100

            services = []
            for service in json['services']['NBN']:  # I only have NBN, if you have something else please get in touch.
                try:
                    service_id = service['service_id']
                    plan = service['plan']
                    description = service['description']
                    next_bill = service['nextBillDate']
                    open_date = service['openDate']
                    rollover_day = service['usageAnniversary']
                    ip_addresses = service['ipAddresses']
                    address = '{} {} {}, {} {} {}'.format(service['address']['streetnumber'],
                                                          service['address']['streetname'],
                                                          service['address']['streettype'],
                                                          service['address']['locality'],
                                                          service['address']['state'],
                                                          service['address']['postcode'])

                    # Prepend the unit type and number if there is one
                    if service['address']['subaddresstype'] and service['address']['subaddressnumber']:
                        address = '{} {}, {}'.format(service['address']['subaddresstype'],
                                                     service['address']['subaddressnumber'], address)

                    # Try to populate the connection details
                    try:
                        connection_type = service['nbnDetails']['product']
                        poi = service['nbnDetails']['poiName']
                        cvc_graph_url = service['nbnDetails']['cvcGraph']
                        download_potential = service['nbnDetails']['speedPotential']['downloadMbps']
                        upload_potential = service['nbnDetails']['speedPotential']['uploadMbps']
                        last_test = service['nbnDetails']['speedPotential']['lastTested']

                        connection_details = NBNDetails(connection_type, poi, cvc_graph_url, download_potential,
                                                        upload_potential, last_test)
                    except Exception:
                        raise Exception('Failed to populate NBNDetails')

                    services.append(
                        NBNService(self, service_id, plan, description, connection_details, next_bill, open_date,
                                   rollover_day, ip_addresses, address))
                except Exception:
                    raise Exception('Failed to populate NBNService')

            return Customer(customer_number, billing_name, bill_format, brand, address, phone, emails, payment_method,
                            suspended, balance, services)
        except Exception:
            raise Exception('Failed to populate Customer')


class Customer:
    """
    An Aussie Broadband customer account.
    Contains everything from postal address and communication preferences to services and account permissions.
    """

    def __init__(self, customer_number, billing_name, bill_format, brand, address, phone, emails, payment_method,
                 suspended, balance, services):
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


class NBNService:
    """
    An NBN Internet service.
    Everything you need to know about an NBN service can be found in here.
    """

    type = 'NBN'
    name = 'NBN'
    contract = None  # <-- What is this?

    @property
    def usage_overview(self):
        # Check if we do not have the data or if it is stale
        if not self._usage_overview or time.time() - self._usage_overview_updated > self._abb_api.cache_refresh:
            self.usage_overview = self._get_usage_overview()
        return self._usage_overview

    @usage_overview.setter
    def usage_overview(self, value):
        self._usage_overview = value
        self._usage_overview_updated = time.time()

    @property
    def historic_usage(self):
        # Check if we do not have the data or it is stale
        if not self._usage_overview or time.time() - self._historic_usage_updated > self._abb_api.cache_refresh:
            self.usage_overview = self._get_usage_overview()
        return self._usage_overview

    @historic_usage.setter
    def historic_usage(self, value):
        self._historic_usage = value
        self._historic_usage_updated = time.time()

    def __init__(self, abb_api, service_id, plan, description, connection_details, next_bill, open_date, rollover_day,
                 ip_addresses, address):
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

    def _get_usage_overview(self):
        req = self._abb_api.authenticated_get('broadband/' + str(self.service_id) + '/usage')

        # Unpack the response JSON
        json = req.json()

        try:
            usage_total = json['usedMb']
            usage_download = json['downloadedMb']
            usage_upload = json['uploadedMb']
            usage_remaining = json['remainingMb']
            days_total = json['daysTotal']
            days_remaining = json['daysRemaining']
            last_update = json['lastUpdated']

            return OverviewServiceUsage(usage_total, usage_download, usage_upload, usage_remaining, days_total,
                                        days_remaining, last_update)
        except Exception:
            raise Exception('Failed to populate ServiceUsageOverview')

    def _get_historic_usage(self, endpoint=None):
        # If we're not using any specific endpoint, use the current month
        if not endpoint:
            current_time = time.localtime()
            endpoint = 'broadband/{}/usage/{}/{}'.format(str(self.service_id), current_time.tm_year, current_time.tm_mon)

        req = self._abb_api.authenticated_get(endpoint)

        # Unpack the response JSON
        json = req.json()

        # Grab and store the results
        _dict = {}
        for day in json['data']:
            date = day['date']
            download = day['download']
            upload = day['upload']

            _dict[date] = HistoricUsage(date, download, upload)

        #



class OverviewServiceUsage:
    """
    Overview usage data for the current month.
    Usage is in megabytes (10^6 bytes).
    """

    def __init__(self, total, download, upload, remaining, days_total, days_remaining, last_update):
        self.total = total
        self.download = download
        self.upload = upload
        self.remaining = remaining
        self.days_total = days_total
        self.days_remaining = days_remaining
        self.last_update = last_update


class HistoricUsageDict:
    """
    Historic usage data dictionary wrapper to handle funky dates.
    Access with YYYY-MM-DD date format. Specifying only YYYY or YYYY-MM will fill in the remaining months and days.
    """

    def __init__(self, abb_api, history={}):
        self._abb_api = abb_api
        self._history = history

    def __getitem__(self, key):
        output = []
        match = re.match(r'^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?$', key) # 4-digit year, optional 1- or 2-digit month, optional 1- or 2-digit day
        if match:
            year = match.group(1)
            month = '{:0>2}'.format(match.group(2)) if match.group(2) else ''  # Pad month with a zero
            day = '{:0>2}'.format(match.group(3)) if match.group(3) else ''  # Pad day with a zero

            # Get everything from that year
            if not month:
                for month in range(1, 12):
                    for day in range(1, 30):
                        key = '{}-{:0<2}-{:0<2}'.format(year, month, day)
                        output.append(self._history[key])
                return output

            # Get everything from that month
            if not day:
                for day in range(1,30):
                    key = '{}-{}-{:0<2}'.format(year, month, day)
                    output.append(self._history[key])
                return output

            # Get the specific day
            key = '{}-{}-{}'.format(year, month, day)
            return self._history[key]
        else:
            raise KeyError()

    def __setitem__(self, key, value):
        """
        Add or update an item within the dictionary.
        All keys must match a YYYY-MM-DD date format.
        :param key: Key to add or update
        :param value: Value to set
        :exception KeyError: Key format does not match YYYY-MM-DD
        """

        if re.match(r'^\d{4}-\d{2}-\d{2}$'):
            self._history[key] = value
        else:
            raise KeyError()


class HistoricUsage:
    """
    Historic usage data.
    Usage is in megabytes (10^6 bytes)
    """

    def __init__(self, date, download=0, upload=0):
        self.date = date
        self.download = download
        self.upload = upload


class NBNDetails:
    """
    Line details for an NBN service.
    Describes the connection type, POI, and speed potential.
    """

    def __init__(self, connection_type, poi, cvc_graph_url, download_potential, upload_potential, last_test):
        self.connection_type = connection_type
        self.poi = poi
        self.cvc_graph_url = cvc_graph_url
        self.download_potential = download_potential
        self.upload_potential = upload_potential
        self.last_test = last_test
