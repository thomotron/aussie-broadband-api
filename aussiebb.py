from datetime import datetime
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
        if self._customer is None or datetime().gmtime() - self._customer_updated > self.cache_refresh:
            self._customer = self._get_customer()
        return self._customer

    @customer.setter
    def customer(self, value):
        self._customer = value

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
        if not self._usage_overview:
            self._usage_overview = self._get_usage_overview()
        return self._usage_overview

    @usage_overview.setter
    def usage_overview(self, value):
        self._usage_overview = value

    # @property
    # def historic_usage(self, year):
    #     if

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

    # def _get_historic_usage(self):
    #     req = self._abb_api.authenticated_get('broadband/' + str(self.service_id) + '/usage/' + )


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


# class HistoricServiceUsage:
#     """
#     Historic usage data.
#     Usage is in megabytes (10^6 bytes).
#     """
#
#     def __init__(self, abb_api):
#         self._abb_api = abb_api
#         self._usage_by_year_then_by_month_then_by_day = {}
#
#     def __getitem__(self, key):
#         if not key in self._usage_by_year_then_by_month_then_by_day:
#             raise KeyError()
#         return self._usage_by_year_then_by_month_then_by_day[key]

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
