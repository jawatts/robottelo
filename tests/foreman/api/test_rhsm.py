"""Tests for the ``rhsm`` paths.

No API doc exists for the subscription manager path(s). However, bugzilla bug
1112802 provides some relevant information.


:Requirement: Rhsm

:CaseAutomation: Automated

:CaseLevel: Acceptance

:CaseComponent: Candlepin

:TestType: Functional

:CaseImportance: High

:Upstream: No
"""
import http

import pytest
from nailgun import client

from robottelo.config import settings


@pytest.mark.tier1
def test_positive_path():
    """Check whether the path exists.

    :id: a8706cb7-549b-4426-9bd9-4beecc33c797

    :expectedresults: Issuing an HTTP GET produces an HTTP 200 response
        with an ``application/json`` content-type, and the response is a
        list.

    :BZ: 1112802

    :CaseImportance: Critical
    """
    path = f'{settings.server.get_url()}/rhsm'
    response = client.get(path, auth=settings.server.get_credentials(), verify=False)
    assert response.status_code == http.client.OK
    assert 'application/json' in response.headers['content-type']
    assert type(response.json()) is list
