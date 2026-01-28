import hashlib
import json
import time
import requests
from django.conf import settings
from django.core.cache import cache


class ODataClient:
    """Client for fetching and caching OData from EMIS warehouse."""

    def __init__(self):
        self.cfg = settings.EMIS
        self.base_url = self.cfg["ODATA_URL"]
        self._token = None
        self._token_time = 0

    def _ensure_token(self):
        """Ensure we have a valid authentication token."""
        # Skip auth if no username/password configured
        if not self.cfg.get("USERNAME") or not self.cfg.get("PASSWORD"):
            return

        # refresh every 30 min
        if self._token and (time.time() - self._token_time) < 1800:
            return
        data = {
            "grant_type": "password",
            "username": self.cfg["USERNAME"],
            "password": self.cfg["PASSWORD"],
        }
        r = requests.post(
            self.cfg["LOGIN_URL"],
            data=data,
            timeout=self.cfg["TIMEOUT_SECONDS"],
            verify=self.cfg["VERIFY_SSL"],
        )
        r.raise_for_status()
        payload = r.json()
        self._token = payload.get("access_token") or payload.get("accessToken")
        self._token_time = time.time()

    def _headers(self):
        """Get authentication headers with Bearer token."""
        self._ensure_token()
        if self._token:
            return {"Authorization": f"Bearer {self._token}"}
        return {}

    def get_enrolment_by_school(
        self,
        filters=None,
        select=None,
        orderby=None,
        top=None
    ):
        """
        Fetch enrollment data by school dimension.

        Args:
            filters: OData $filter string (e.g., "SurveyYear eq 2024 and SchoolNo eq 'SCH001'")
            select: List of fields to select (e.g., ['SchoolNo', 'SchoolName', 'Enrol'])
            orderby: OData $orderby string (e.g., "SchoolName asc")
            top: Limit results (e.g., 100)

        Returns:
            List of dictionaries with enrollment data

        Example:
            client = ODataClient()
            data = client.get_enrolment_by_school(
                filters="SurveyYear eq 2024 and SchoolNo eq 'SCH001'",
                select=['SchoolNo', 'SchoolName', 'ClassLevel', 'Enrol', 'Disab']
            )
        """
        endpoint = f"{self.base_url}/EnrolSchool"
        return self._fetch_odata(endpoint, filters, select, orderby, top)

    def get_enrolment_by_district(
        self,
        filters=None,
        select=None,
        orderby=None,
        top=None
    ):
        """
        Fetch enrollment data aggregated by district.

        Args:
            filters: OData $filter string
            select: List of fields to select
            orderby: OData $orderby string
            top: Limit results

        Returns:
            List of dictionaries with district enrollment data
        """
        endpoint = f"{self.base_url}/EnrolDistrict"
        return self._fetch_odata(endpoint, filters, select, orderby, top)

    def get_enrolment_by_authority(
        self,
        filters=None,
        select=None,
        orderby=None,
        top=None
    ):
        """
        Fetch enrollment data aggregated by authority.

        Args:
            filters: OData $filter string
            select: List of fields to select
            orderby: OData $orderby string
            top: Limit results

        Returns:
            List of dictionaries with authority enrollment data
        """
        endpoint = f"{self.base_url}/EnrolAuthority"
        return self._fetch_odata(endpoint, filters, select, orderby, top)

    def get_enrolment_by_nation(
        self,
        filters=None,
        select=None,
        orderby=None,
        top=None
    ):
        """
        Fetch enrollment data aggregated at national level.

        Args:
            filters: OData $filter string
            select: List of fields to select
            orderby: OData $orderby string
            top: Limit results

        Returns:
            List of dictionaries with national enrollment data
        """
        endpoint = f"{self.base_url}/EnrolNation"
        return self._fetch_odata(endpoint, filters, select, orderby, top)

    def invalidate_cache(self, endpoint_suffix, filters=None, select=None, orderby=None, top=None):
        """
        Manually invalidate specific cached query.

        Args:
            endpoint_suffix: The endpoint name (e.g., "EnrolSchool", "EnrolDistrict")
            filters: OData $filter string (must match original query)
            select: List of fields (must match original query)
            orderby: OData $orderby string (must match original query)
            top: Limit (must match original query)
        """
        endpoint = f"{self.base_url}/{endpoint_suffix}"
        params = self._build_odata_params(filters, select, orderby, top)
        cache_key = self._generate_cache_key(endpoint, params)
        cache.delete(cache_key)

    def clear_all_cache(self):
        """
        Clear all cached OData queries.
        Note: This uses Django's cache.clear() which clears the entire cache.
        """
        cache.clear()

    def _fetch_odata(self, endpoint, filters, select, orderby, top):
        """Internal method to fetch data from OData endpoint with pagination."""
        import logging

        logger = logging.getLogger(__name__)

        params = self._build_odata_params(filters, select, orderby, top)

        # Fetch all pages from OData
        logger.info(f"ODataClient: Fetching data from {endpoint}")
        all_data = []
        next_url = endpoint
        page_num = 1

        while next_url:
            logger.info(f"ODataClient: Fetching page {page_num}...")

            # First page uses params, subsequent pages use the nextLink URL directly
            if page_num == 1:
                response = requests.get(
                    next_url,
                    params=params,
                    timeout=60,  # Longer timeout for large datasets
                    verify=self.cfg["VERIFY_SSL"]
                )
            else:
                # For continuation URLs, params are already in the URL
                response = requests.get(
                    next_url,
                    timeout=60,
                    verify=self.cfg["VERIFY_SSL"]
                )

            response.raise_for_status()
            response_json = response.json()

            page_data = response_json.get("value", [])
            all_data.extend(page_data)
            logger.info(f"ODataClient: Page {page_num} returned {len(page_data)} records (total: {len(all_data)})")

            # Check for next page - OData v4 uses @odata.nextLink, v3 uses odata.nextLink
            next_url = response_json.get("@odata.nextLink") or response_json.get("odata.nextLink")

            if next_url:
                logger.info(f"ODataClient: Next page available")
                page_num += 1

                # Safety check to prevent infinite loops
                if page_num > 200:
                    logger.warning(f"ODataClient: Reached maximum page limit (200), stopping")
                    break
            else:
                logger.info(f"ODataClient: No more pages, fetched {len(all_data)} total records")

        return all_data

    def _build_odata_params(self, filters, select, orderby, top):
        """Build OData query parameters."""
        params = {}
        if filters:
            params["$filter"] = filters
        if select:
            params["$select"] = ",".join(select) if isinstance(select, list) else select
        if orderby:
            params["$orderby"] = orderby
        if top:
            params["$top"] = top
        return params

    def _generate_cache_key(self, endpoint, params):
        """Generate a unique cache key from endpoint and params."""
        key_data = f"{endpoint}:{json.dumps(params, sort_keys=True)}"
        hash_key = hashlib.md5(key_data.encode()).hexdigest()
        return f"odata:{hash_key}"


def load_enrollment_cache():
    """
    Load pre-aggregated enrollment data from filesystem cache.

    This data is synced via the 'sync_enrollment_data' management command.
    Returns aggregated enrollment records or None if cache doesn't exist.

    Returns:
        list: List of dicts with keys: SurveyYear, SchoolNo, SchoolName, GenderCode, Enrol
        None: If cache file doesn't exist

    Example usage:
        enrollment_data = load_enrollment_cache()
        if enrollment_data:
            # Fast access to pre-aggregated data
            for record in enrollment_data:
                print(record['SurveyYear'], record['SchoolNo'], record['Enrol'])
    """
    import pickle
    from pathlib import Path

    data_dir = Path(settings.BASE_DIR) / "data"

    # Try pickle format first (faster)
    cache_file = data_dir / "enrollment_aggregated.pickle"
    if cache_file.exists():
        try:
            with open(cache_file, 'rb') as f:
                return pickle.load(f)
        except Exception:
            pass

    # Fallback to JSON format
    cache_file = data_dir / "enrollment_aggregated.json"
    if cache_file.exists():
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass

    return None
