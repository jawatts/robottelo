"""Unit tests for the ``repositories`` paths.

:Requirement: Repository

:CaseAutomation: Automated

:CaseLevel: Component

:CaseComponent: Repositories

:TestType: Functional

:CaseImportance: High

:Upstream: No
"""
import tempfile
from urllib.parse import urljoin

import pytest
from fauxfactory import gen_string
from nailgun import client
from nailgun import entities
from nailgun.entity_mixins import TaskFailedError
from requests.exceptions import HTTPError
from requests.exceptions import SSLError

from robottelo import manifests
from robottelo import ssh
from robottelo.api.utils import call_entity_method_with_timeout
from robottelo.api.utils import enable_rhrepo_and_fetchid
from robottelo.api.utils import promote
from robottelo.api.utils import upload_manifest
from robottelo.config import settings
from robottelo.constants import CHECKSUM_TYPE
from robottelo.constants import DOCKER_REGISTRY_HUB
from robottelo.constants import DOCKER_UPSTREAM_NAME
from robottelo.constants import DOWNLOAD_POLICIES
from robottelo.constants import FAKE_0_YUM_REPO_STRING_BASED_VERSIONS_COUNTS
from robottelo.constants import PRDS
from robottelo.constants import REPO_TYPE
from robottelo.constants import REPOS
from robottelo.constants import REPOSET
from robottelo.constants import RPM_TO_UPLOAD
from robottelo.constants import SRPM_TO_UPLOAD
from robottelo.constants import VALID_GPG_KEY_BETA_FILE
from robottelo.constants import VALID_GPG_KEY_FILE
from robottelo.constants.repos import CUSTOM_MODULE_STREAM_REPO_1
from robottelo.constants.repos import CUSTOM_MODULE_STREAM_REPO_2
from robottelo.constants.repos import FAKE_0_PUPPET_REPO
from robottelo.constants.repos import FAKE_0_YUM_REPO_STRING_BASED_VERSIONS
from robottelo.constants.repos import FAKE_1_PUPPET_REPO
from robottelo.constants.repos import FAKE_2_YUM_REPO
from robottelo.constants.repos import FAKE_5_YUM_REPO
from robottelo.constants.repos import FAKE_7_PUPPET_REPO
from robottelo.constants.repos import FAKE_YUM_DRPM_REPO
from robottelo.constants.repos import FAKE_YUM_SRPM_DUPLICATE_REPO
from robottelo.constants.repos import FAKE_YUM_SRPM_REPO
from robottelo.constants.repos import FEDORA26_OSTREE_REPO
from robottelo.constants.repos import FEDORA27_OSTREE_REPO
from robottelo.datafactory import invalid_http_credentials
from robottelo.datafactory import invalid_names_list
from robottelo.datafactory import invalid_values_list
from robottelo.datafactory import parametrized
from robottelo.datafactory import valid_data_list
from robottelo.datafactory import valid_docker_repository_names
from robottelo.datafactory import valid_http_credentials
from robottelo.datafactory import valid_labels_list
from robottelo.decorators import skip_if_not_set
from robottelo.helpers import get_data_file
from robottelo.helpers import read_data_file


@pytest.fixture
def repo_options(request, module_org, module_product):
    """Return the options that were passed as indirect parameters."""
    options = getattr(request, 'param', {}).copy()
    options['organization'] = module_org
    options['product'] = module_product
    return options


@pytest.fixture
def env(module_org):
    """Create a new puppet environment."""
    return entities.Environment(organization=[module_org]).create()


@pytest.fixture
def repo(repo_options):
    """Create a new repository."""
    return entities.Repository(**repo_options).create()


@pytest.fixture
def http_proxy(module_org):
    """Create a new HTTP proxy."""
    return entities.HTTPProxy(
        name=gen_string('alpha', 15),
        url=settings.http_proxy.auth_proxy_url,
        username=settings.http_proxy.username,
        password=settings.http_proxy.password,
        organization=[module_org.id],
    ).create()


class TestRepository:
    """Tests for ``katello/api/v2/repositories``."""

    @pytest.mark.tier1
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized([{'name': name} for name in valid_data_list().values()]),
        indirect=True,
    )
    def test_positive_create_with_name(self, repo_options, repo):
        """Create a repository with valid name.

        :id: 159f7296-55d2-4360-948f-c24e7d75b962

        :parametrized: yes

        :expectedresults: A repository is created with the given name.

        :CaseImportance: Critical
        """
        assert repo_options['name'] == repo.name

    @pytest.mark.tier2
    @pytest.mark.upgrade
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    def test_positive_assign_http_proxy_to_repository(
        self, module_org, module_product, http_proxy
    ):
        """Assign http_proxy to Repositories and perform repository sync.

        :id: 5b3b992e-02d3-4b16-95ed-21f1588c7741

        :expectedresults: HTTP Proxy can be assigned to repository and sync operation performed
            successfully.

        :CaseImportance: Critical
        """
        repo_options = {
            'http_proxy_policy': 'use_selected_http_proxy',
            'http_proxy_id': http_proxy.id,
        }
        repo = entities.Repository(**repo_options).create()

        assert repo.http_proxy_policy == repo_options['http_proxy_policy']
        assert repo.http_proxy_id == http_proxy.id
        repo.sync()
        assert repo.read().content_counts['rpm'] >= 1

        # Use global_default_http_proxy
        repo_options['http_proxy_policy'] = 'global_default_http_proxy'
        repo_2 = entities.Repository(**repo_options).create()
        assert repo_2.http_proxy_policy == 'global_default_http_proxy'

        # Update to selected_http_proxy
        repo_2.http_proxy_policy = 'none'
        repo_2.update(['http_proxy_policy'])
        assert repo_2.http_proxy_policy == 'none'

    @pytest.mark.tier1
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized([{'label': label} for label in valid_labels_list()]),
        indirect=True,
    )
    def test_positive_create_with_label(self, repo_options, repo):
        """Create a repository providing label which is different from its name

        :id: 3be1b3fa-0e17-416f-97f0-858709e6b1da

        :parametrized: yes

        :expectedresults: A repository is created with expected label.

        :CaseImportance: Critical
        """
        assert repo.label == repo_options['label']
        assert repo.name != repo_options['label']

    @pytest.mark.tier1
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized([{'content_type': 'yum', 'url': FAKE_2_YUM_REPO}]),
        indirect=True,
    )
    def test_positive_create_yum(self, repo_options, repo):
        """Create yum repository.

        :id: 7bac7f45-0fb3-4443-bb3b-cee72248ca5d

        :parametrized: yes

        :expectedresults: A repository is created and has yum type.

        :CaseImportance: Critical
        """
        for k in 'content_type', 'url':
            assert getattr(repo, k) == repo_options[k]

    @pytest.mark.tier1
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized([{'content_type': 'puppet', 'url': FAKE_0_PUPPET_REPO}]),
        indirect=True,
    )
    def test_positive_create_puppet(self, repo_options, repo):
        """Create puppet repository.

        :id: daa10ded-6de3-44b3-9707-9f0ac983d2ea

        :parametrized: yes

        :expectedresults: A repository is created and has puppet type.

        :CaseImportance: Critical
        """
        assert repo.content_type == repo_options['content_type']

    @pytest.mark.tier1
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized(
            [
                {
                    'content_type': 'yum',
                    'url': FAKE_5_YUM_REPO.format(creds['login'], creds['pass']),
                }
                for creds in valid_http_credentials(url_encoded=True)
            ]
        ),
        indirect=True,
    )
    def test_positive_create_with_auth_yum_repo(self, repo_options, repo):
        """Create yum repository with basic HTTP authentication

        :id: 1b17fe37-cdbf-4a79-9b0d-6813ea502754

        :parametrized: yes

        :expectedresults: yum repository is created

        :CaseImportance: Critical
        """
        for k in 'content_type', 'url':
            assert getattr(repo, k) == repo_options[k]

    @pytest.mark.tier1
    @pytest.mark.upgrade
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized(
            [{'content_type': 'yum', 'download_policy': policy} for policy in DOWNLOAD_POLICIES]
        ),
        indirect=True,
    )
    def test_positive_create_with_download_policy(self, repo_options, repo):
        """Create YUM repositories with available download policies

        :id: 5e5479c4-904d-4892-bc43-6f81fa3813f8

        :parametrized: yes

        :expectedresults: YUM repository with a download policy is created

        :CaseImportance: Critical
        """
        assert repo.download_policy == repo_options['download_policy']

    @pytest.mark.tier1
    @pytest.mark.parametrize(
        'repo_options', **parametrized([{'content_type': 'yum'}]), indirect=True
    )
    def test_positive_create_with_default_download_policy(self, repo):
        """Verify if the default download policy is assigned
        when creating a YUM repo without `download_policy` field

        :id: 54108f30-d73e-46d3-ae56-cda28678e7e9

        :parametrized: yes

        :expectedresults: YUM repository with a default download policy

        :CaseImportance: Critical
        """

        default_dl_policy = entities.Setting().search(
            query={'search': 'name=default_download_policy'}
        )
        assert default_dl_policy
        assert repo.download_policy == default_dl_policy[0].value

    @pytest.mark.tier1
    @pytest.mark.parametrize(
        'repo_options', **parametrized([{'content_type': 'yum'}]), indirect=True
    )
    def test_positive_create_immediate_update_to_on_demand(self, repo):
        """Update `immediate` download policy to `on_demand`
        for a newly created YUM repository

        :id: 8a70de9b-4663-4251-b91e-d3618ee7ef84

        :parametrized: yes

        :expectedresults: immediate download policy is updated to on_demand

        :CaseImportance: Critical

        :BZ: 1732056
        """
        assert repo.download_policy == 'immediate'

        # Update repo 'download_policy' to 'on_demand'
        repo.download_policy = 'on_demand'
        repo = repo.update(['download_policy'])
        assert repo.download_policy == 'on_demand'

    @pytest.mark.tier1
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized([{'content_type': 'yum', 'download_policy': 'immediate'}]),
        indirect=True,
    )
    def test_positive_create_immediate_update_to_background(self, repo):
        """Update `immediate` download policy to `background`
        for a newly created YUM repository

        :id: 9aaf53be-1127-4559-9faf-899888a52846

        :parametrized: yes

        :expectedresults: immediate download policy is updated to background

        :CaseImportance: Critical
        """
        repo.download_policy = 'background'
        repo = repo.update(['download_policy'])
        assert repo.download_policy == 'background'

    @pytest.mark.tier1
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized([{'content_type': 'yum', 'download_policy': 'on_demand'}]),
        indirect=True,
    )
    def test_positive_create_on_demand_update_to_immediate(self, repo):
        """Update `on_demand` download policy to `immediate`
        for a newly created YUM repository

        :id: 589ff7bb-4251-4218-bb90-4e63c9baf702

        :parametrized: yes

        :expectedresults: on_demand download policy is updated to immediate

        :CaseImportance: Critical
        """
        repo.download_policy = 'immediate'
        repo = repo.update(['download_policy'])
        assert repo.download_policy == 'immediate'

    @pytest.mark.tier1
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized([{'content_type': 'yum', 'download_policy': 'on_demand'}]),
        indirect=True,
    )
    def test_positive_create_on_demand_update_to_background(self, repo):
        """Update `on_demand` download policy to `background`
        for a newly created YUM repository

        :id: 1d9888a0-c5b5-41a7-815d-47e936022a60

        :parametrized: yes

        :expectedresults: on_demand download policy is updated to background

        :CaseImportance: Critical
        """
        repo.download_policy = 'background'
        repo = repo.update(['download_policy'])
        assert repo.download_policy == 'background'

    @pytest.mark.tier1
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized([{'content_type': 'yum', 'download_policy': 'background'}]),
        indirect=True,
    )
    def test_positive_create_background_update_to_immediate(self, repo):
        """Update `background` download policy to `immediate`
        for a newly created YUM repository

        :id: 169530a7-c5ce-4ca5-8cdd-15398e13e2af

        :parametrized: yes

        :expectedresults: background download policy is updated to immediate

        :CaseImportance: Critical
        """
        repo.download_policy = 'immediate'
        repo = repo.update(['download_policy'])
        assert repo.download_policy == 'immediate'

    @pytest.mark.tier1
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized([{'content_type': 'yum', 'download_policy': 'background'}]),
        indirect=True,
    )
    def test_positive_create_background_update_to_on_demand(self, repo):
        """Update `background` download policy to `on_demand`
        for a newly created YUM repository

        :id: 40a3e963-61ff-41c4-aa6c-d9a4a638af4a

        :parametrized: yes

        :expectedresults: background download policy is updated to on_demand

        :CaseImportance: Critical
        """
        repo.download_policy = 'on_demand'
        repo = repo.update(['download_policy'])
        assert repo.download_policy == 'on_demand'

    @pytest.mark.tier1
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized(
            [
                {
                    'content_type': 'puppet',
                    'url': FAKE_7_PUPPET_REPO.format(creds['login'], creds['pass']),
                }
                for creds in valid_http_credentials(url_encoded=True)
            ]
        ),
        indirect=True,
    )
    def test_positive_create_with_auth_puppet_repo(self, repo_options, repo):
        """Create Puppet repository with basic HTTP authentication

        :id: af9e4f0f-d128-43d2-a680-0a62c7dab266

        :parametrized: yes

        :expectedresults: Puppet repository is created

        :CaseImportance: Critical
        """
        assert repo.content_type == repo_options['content_type']
        assert repo.url == repo_options['url']

    @pytest.mark.tier1
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized(
            [
                {'checksum_type': checksum_type, 'download_policy': 'immediate'}
                for checksum_type in ('sha1', 'sha256')
            ]
        ),
        indirect=True,
    )
    def test_positive_create_checksum(self, repo_options, repo):
        """Create a repository with valid checksum type.

        :id: c3678878-758a-4501-a038-a59503fee453

        :parametrized: yes

        :expectedresults: A repository is created and has expected checksum
            type.

        :CaseImportance: Critical
        """
        assert repo.checksum_type == repo_options['checksum_type']

    @pytest.mark.tier1
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized(
            [
                {'checksum_type': checksum_type, 'download_policy': 'background'}
                for checksum_type in (CHECKSUM_TYPE['sha1'], CHECKSUM_TYPE['sha256'])
            ]
        ),
        indirect=True,
    )
    def test_positive_create_checksum_with_background_policy(self, repo_options, repo):
        """Attempt to create repository with checksum and background policy.

        :id: 4757ae21-f792-4886-a86a-799949ad82d0

        :parametrized: yes

        :expectedresults: A repository is created and has expected checksum type.

        :CaseImportance: Critical
        """
        assert repo.checksum_type == repo_options['checksum_type']

    @pytest.mark.tier1
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized([{'unprotected': unprotected} for unprotected in (True, False)]),
        indirect=True,
    )
    def test_positive_create_unprotected(self, repo_options, repo):
        """Create a repository with valid unprotected flag values.

        :id: 38f78733-6a72-4bf5-912a-cfc51658f80c

        :parametrized: yes

        :expectedresults: A repository is created and has expected unprotected
            flag state.

        :CaseImportance: Critical
        """
        assert repo.unprotected == repo_options['unprotected']

    @pytest.mark.tier2
    def test_positive_create_with_gpg(self, module_org, module_product):
        """Create a repository and provide a GPG key ID.

        :id: 023cf84b-74f3-4e63-a9d7-10afee6c1990

        :expectedresults: A repository is created with the given GPG key ID.

        :CaseLevel: Integration
        """
        gpg_key = entities.GPGKey(
            organization=module_org, content=read_data_file(VALID_GPG_KEY_FILE)
        ).create()
        repo = entities.Repository(product=module_product, gpg_key=gpg_key).create()
        # Verify that the given GPG key ID is used.
        assert repo.gpg_key.id == gpg_key.id

    @pytest.mark.tier2
    def test_positive_create_same_name_different_orgs(self, repo):
        """Create two repos with the same name in two different organizations.

        :id: bd1bd7e3-e393-44c8-a6d0-42edade40f60

        :expectedresults: The two repositories are successfully created and
            have given name.

        :CaseLevel: Integration
        """
        org_2 = entities.Organization().create()
        product_2 = entities.Product(organization=org_2).create()
        repo_2 = entities.Repository(product=product_2, name=repo.name).create()
        assert repo_2.name == repo.name

    @pytest.mark.tier2
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized(
            [{'content_type': 'puppet', 'url': 'https://omaciel.fedorapeople.org/7c74c2b8/'}]
        ),
        indirect=True,
    )
    def test_positive_create_puppet_repo_same_url_different_orgs(self, repo_options, repo):
        """Create two repos with the same URL in two different organizations.

        :id: 7c74c2b8-732a-4c47-8ad9-697121db05be

        :parametrized: yes

        :expectedresults: Repositories are created and puppet modules are
            visible from different organizations.

        :CaseLevel: Integration
        """
        repo.sync()
        assert repo.read().content_counts['puppet_module'] >= 1

        # Create new org, product, and repo
        org_2 = entities.Organization().create()
        product_2 = entities.Product(organization=org_2).create()
        repo_options_2 = repo_options.copy()
        repo_options_2['organization'] = org_2
        repo_options_2['product'] = product_2
        repo_2 = entities.Repository(**repo_options_2).create()
        repo_2.sync()
        assert repo_2.read().content_counts['puppet_module'] >= 1

    @pytest.mark.tier1
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized([{'name': name} for name in invalid_values_list()]),
        indirect=True,
    )
    def test_negative_create_name(self, repo_options):
        """Attempt to create repository with invalid names only.

        :id: 24947c92-3415-43df-add6-d6eb38afd8a3

        :parametrized: yes

        :expectedresults: A repository is not created and error is raised.

        :CaseImportance: Critical
        """
        with pytest.raises(HTTPError):
            entities.Repository(**repo_options).create()

    @pytest.mark.tier1
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized([{'name': name} for name in valid_data_list().values()]),
        indirect=True,
    )
    def test_negative_create_with_same_name(self, repo_options, repo):
        """Attempt to create a repository providing a name of already existent
        entity

        :id: 0493dfc4-0043-4682-b339-ce61da7d48ae

        :parametrized: yes

        :expectedresults: Second repository is not created

        :CaseImportance: Critical
        """
        with pytest.raises(HTTPError):
            entities.Repository(**repo_options).create()

    @pytest.mark.tier1
    def test_negative_create_label(self, module_product):
        """Attempt to create repository with invalid label.

        :id: f646ae84-2660-41bd-9883-331285fa1c9a

        :expectedresults: A repository is not created and error is raised.

        :CaseImportance: Critical
        """
        with pytest.raises(HTTPError):
            entities.Repository(product=module_product, label=gen_string('utf8')).create()

    @pytest.mark.tier1
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized([{'url': url} for url in invalid_names_list()]),
        indirect=True,
    )
    def test_negative_create_url(self, repo_options):
        """Attempt to create repository with invalid url.

        :id: 0bb9fc3f-d442-4437-b5d8-83024bc7ceab

        :parametrized: yes

        :expectedresults: A repository is not created and error is raised.

        :CaseImportance: Critical
        """
        with pytest.raises(HTTPError):
            entities.Repository(**repo_options).create()

    @pytest.mark.tier1
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized(
            [
                {'url': FAKE_5_YUM_REPO.format(cred['login'], cred['pass'])}
                for cred in valid_http_credentials()
                if cred['quote']
            ]
        ),
        indirect=True,
    )
    def test_negative_create_with_auth_url_with_special_characters(self, repo_options):
        """Verify that repository URL cannot contain unquoted special characters

        :id: 2ffaa412-e5e5-4bec-afaa-9ea54315df49

        :parametrized: yes

        :expectedresults: A repository is not created and error is raised.

        :CaseImportance: Critical
        """
        with pytest.raises(HTTPError):
            entities.Repository(**repo_options).create()

    @pytest.mark.tier1
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized(
            [
                {'url': FAKE_5_YUM_REPO.format(cred['login'], cred['pass'])}
                for cred in invalid_http_credentials()
            ]
        ),
        indirect=True,
    )
    def test_negative_create_with_auth_url_too_long(self, repo_options):
        """Verify that repository URL length is limited

        :id: 5aad4e9f-f7e1-497c-8e1f-55e07e38ee80

        :parametrized: yes

        :expectedresults: A repository is not created and error is raised.

        :CaseImportance: Critical
        """
        with pytest.raises(HTTPError):
            entities.Repository(**repo_options).create()

    @pytest.mark.tier1
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized([{'content_type': 'yum', 'download_policy': gen_string('alpha', 5)}]),
        indirect=True,
    )
    def test_negative_create_with_invalid_download_policy(self, repo_options):
        """Verify that YUM repository cannot be created with invalid
        download policy

        :id: c39bf33a-26f6-411b-8658-eab1bb40ef84

        :parametrized: yes

        :expectedresults: YUM repository is not created with invalid download
            policy

        :CaseImportance: Critical
        """
        with pytest.raises(HTTPError):
            entities.Repository(**repo_options).create()

    @pytest.mark.tier1
    @pytest.mark.parametrize(
        'repo_options', **parametrized([{'content_type': 'yum'}]), indirect=True
    )
    def test_negative_update_to_invalid_download_policy(self, repo):
        """Verify that YUM repository cannot be updated to invalid
        download policy

        :id: 24d36e79-855e-4832-a136-30cbd144de44

        :parametrized: yes

        :expectedresults: YUM repository is not updated to invalid download
            policy

        :CaseImportance: Critical
        """
        repo.download_policy = gen_string('alpha', 5)
        with pytest.raises(HTTPError):
            repo.update(['download_policy'])

    @pytest.mark.tier1
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized(
            [
                {'content_type': content_type, 'download_policy': 'on_demand'}
                for content_type in REPO_TYPE.keys()
                if content_type != 'yum'
            ]
        ),
        indirect=True,
    )
    def test_negative_create_non_yum_with_download_policy(self, repo_options):
        """Verify that non-YUM repositories cannot be created with
        download policy

        :id: 8a59cb31-164d-49df-b3c6-9b90634919ce

        :parametrized: yes

        :expectedresults: Non-YUM repository is not created with a download
            policy

        :CaseImportance: Critical
        """
        with pytest.raises(HTTPError):
            entities.Repository(**repo_options).create()

    @pytest.mark.tier1
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized([{'checksum_type': gen_string('alpha'), 'download_policy': 'immediate'}]),
        indirect=True,
    )
    def test_negative_create_checksum(self, repo_options):
        """Attempt to create repository with invalid checksum type.

        :id: c49a3c49-110d-4b74-ae14-5c9494a4541c

        :parametrized: yes

        :expectedresults: A repository is not created and error is raised.

        :CaseImportance: Critical
        """
        with pytest.raises(HTTPError):
            entities.Repository(**repo_options).create()

    @pytest.mark.tier1
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized(
            [
                {'checksum_type': checksum_type, 'download_policy': 'on_demand'}
                for checksum_type in ('sha1', 'sha256')
            ]
        ),
        indirect=True,
    )
    def test_negative_create_checksum_with_on_demand_policy(self, repo_options):
        """Attempt to create repository with checksum and on_demand policy.

        :id: de8b157c-ed62-454b-94eb-22659ce1158e

        :parametrized: yes

        :expectedresults: A repository is not created and error is raised.

        :CaseImportance: Critical
        """
        with pytest.raises(HTTPError):
            entities.Repository(**repo_options).create()

    @pytest.mark.tier1
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized(
            [
                {'checksum_type': checksum_type, 'download_policy': 'immediate'}
                for checksum_type in ('sha1', 'sha256')
            ]
        ),
        indirect=True,
    )
    def test_negative_update_checksum_with_on_demand_policy(self, repo):
        """Attempt to update the download policy to on_demand on a repository with checksum type.

        :id: 5bfaef4f-de66-42a0-8419-b86d00ffde6f

        :parametrized: yes

        :expectedresults: A repository is not updated and error is raised.

        :CaseImportance: Critical
        """
        repo.download_policy = 'on_demand'
        with pytest.raises(HTTPError):
            repo.update(['download_policy'])

    @pytest.mark.tier1
    @pytest.mark.parametrize('name', **parametrized(valid_data_list().values()))
    def test_positive_update_name(self, repo, name):
        """Update repository name to another valid name.

        :id: 1b428129-7cf9-449b-9e3b-74360c5f9eca

        :parametrized: yes

        :expectedresults: The repository name can be updated.

        :CaseImportance: Critical
        """
        repo.name = name
        repo = repo.update(['name'])
        assert repo.name == name

    @pytest.mark.tier1
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized(
            [
                {'checksum_type': checksum_type, 'download_policy': 'immediate'}
                for checksum_type in ('sha1', 'sha256')
            ]
        ),
        indirect=True,
    )
    def test_positive_update_checksum(self, repo_options, repo):
        """Update repository checksum type to another valid one.

        :id: 205e6e59-33c6-4a58-9245-1cac3a4f550a

        :parametrized: yes

        :expectedresults: The repository checksum type can be updated.

        :CaseImportance: Critical
        """
        updated_checksum = 'sha256' if repo_options['checksum_type'] == 'sha1' else 'sha1'
        repo.checksum_type = updated_checksum
        repo = repo.update(['checksum_type'])
        assert repo.checksum_type == updated_checksum

    @pytest.mark.tier1
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    def test_positive_update_url(self, repo):
        """Update repository url to another valid one.

        :id: 8fbc11f0-a5c5-498e-a314-87958dcd7832

        :expectedresults: The repository url can be updated.

        :CaseImportance: Critical
        """
        repo.url = FAKE_2_YUM_REPO
        repo = repo.update(['url'])
        assert repo.url == FAKE_2_YUM_REPO

    @pytest.mark.tier1
    @pytest.mark.parametrize(
        'repo_options', **parametrized([{'unprotected': False}]), indirect=True
    )
    def test_positive_update_unprotected(self, repo):
        """Update repository unprotected flag to another valid one.

        :id: c55d169a-8f11-4bf8-9913-b3d39fee75f0

        :parametrized: yes

        :expectedresults: The repository unprotected flag can be updated.

        :CaseImportance: Critical
        """
        repo.unprotected = True
        repo = repo.update(['unprotected'])
        assert repo.unprotected is True

    @pytest.mark.tier2
    def test_positive_update_gpg(self, module_org, module_product):
        """Create a repository and update its GPGKey

        :id: 0e9319dc-c922-4ecf-9f83-d221cfdf54c2

        :expectedresults: The updated repository points to a new GPG key.

        :CaseLevel: Integration
        """
        # Create a repo and make it point to a GPG key.
        gpg_key_1 = entities.GPGKey(
            organization=module_org, content=read_data_file(VALID_GPG_KEY_FILE)
        ).create()
        repo = entities.Repository(product=module_product, gpg_key=gpg_key_1).create()

        # Update the repo and make it point to a new GPG key.
        gpg_key_2 = entities.GPGKey(
            organization=module_org, content=read_data_file(VALID_GPG_KEY_BETA_FILE)
        ).create()

        repo.gpg_key = gpg_key_2
        repo = repo.update(['gpg_key'])
        assert repo.gpg_key.id == gpg_key_2.id

    @pytest.mark.tier2
    def test_positive_update_contents(self, repo):
        """Create a repository and upload RPM contents.

        :id: 8faa64f9-b620-4c0a-8c80-801e8e6436f1

        :expectedresults: The repository's contents include one RPM.

        :CaseLevel: Integration
        """
        # Upload RPM content.
        with open(get_data_file(RPM_TO_UPLOAD), 'rb') as handle:
            repo.upload_content(files={'content': handle})
        # Verify the repository's contents.
        assert repo.read().content_counts['rpm'] == 1

    @pytest.mark.tier1
    @pytest.mark.upgrade
    def test_positive_upload_delete_srpm(self, repo):
        """Create a repository and upload, delete SRPM contents.

        :id: e091a725-048f-44ca-90cc-c016c450ced9

        :expectedresults: The repository's contents include one SRPM and delete after that.

        :CaseImportance: Critical

        :BZ: 1378442
        """
        # upload srpm
        entities.ContentUpload(repository=repo).upload(
            filepath=get_data_file(SRPM_TO_UPLOAD), content_type='srpm'
        )
        assert repo.read().content_counts['srpm'] == 1
        srpm_detail = entities.Srpms().search(query={'repository_id': repo.id})
        assert len(srpm_detail) == 1

        # Delete srpm
        repo.remove_content(data={'ids': [srpm_detail[0].id], 'content_type': 'srpm'})
        assert repo.read().content_counts['srpm'] == 0

    @pytest.mark.tier1
    @pytest.mark.upgrade
    @pytest.mark.skip('Uses deprecated SRPM repository')
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    @pytest.mark.parametrize(
        'repo_options', **parametrized([{'url': FAKE_YUM_SRPM_REPO}]), indirect=True
    )
    def test_positive_create_delete_srpm_repo(self, repo):
        """Create a repository, sync SRPM contents and remove repo

        :id: e091a725-042f-43ca-99cc-c017c450ced9

        :parametrized: yes

        :expectedresults: The repository's contents include SRPM and able to remove repo

        :CaseImportance: Critical
        """
        repo.sync()
        assert repo.read().content_counts['srpm'] == 3
        assert len(entities.Srpms().search(query={'repository_id': repo.id})) == 3
        repo.delete()
        with pytest.raises(HTTPError):
            repo.read()

    @pytest.mark.tier1
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized([{'content_type': 'yum', 'url': FAKE_2_YUM_REPO}]),
        indirect=True,
    )
    def test_positive_remove_contents(self, repo):
        """Synchronize a repository and remove rpm content.

        :id: f686b74b-7ee9-4806-b999-bc05ffe61a9d

        :parametrized: yes

        :expectedresults: The repository's content is removed and content count
            shows zero packages

        :BZ: 1459845

        :CaseImportance: Critical
        """
        repo.sync()
        assert repo.read().content_counts['rpm'] >= 1
        # Find repo packages and remove them
        packages = entities.Package(repository=repo).search(query={'per_page': '1000'})
        repo.remove_content(data={'ids': [package.id for package in packages]})
        assert repo.read().content_counts['rpm'] == 0

    @pytest.mark.tier1
    @pytest.mark.parametrize('name', **parametrized(invalid_values_list()))
    def test_negative_update_name(self, repo, name):
        """Attempt to update repository name to invalid one

        :id: 6f2f41a4-d871-4b91-87b1-a5a401c4aa69

        :parametrized: yes

        :expectedresults: Repository is not updated

        :CaseImportance: Critical
        """
        repo.name = name
        with pytest.raises(HTTPError):
            repo.update(['name'])

    @pytest.mark.skip_if_open('BZ:1311113')
    @pytest.mark.tier1
    def test_negative_update_label(self, repo):
        """Attempt to update repository label to another one.

        :id: 828d85df-3c25-4a69-b6a2-401c6b82e4f3

        :expectedresults: Repository is not updated and error is raised

        :CaseImportance: Critical

        :BZ: 1311113
        """
        repo.label = gen_string('alpha')
        with pytest.raises(HTTPError):
            repo.update(['label'])

    @pytest.mark.tier1
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    @pytest.mark.parametrize(
        'url',
        **parametrized(
            [
                repo.format(cred['login'], cred['pass'])
                for cred in valid_http_credentials()
                if cred['quote']
                for repo in (FAKE_5_YUM_REPO, FAKE_7_PUPPET_REPO)
            ]
        ),
    )
    def test_negative_update_auth_url_with_special_characters(self, repo, url):
        """Verify that repository URL credentials cannot be updated to contain
        the forbidden characters

        :id: 47530b1c-e964-402a-a633-c81583fb5b98

        :parametrized: yes

        :expectedresults: Repository url not updated

        :CaseImportance: Critical
        """
        repo.url = url
        with pytest.raises(HTTPError):
            repo.update(['url'])

    @pytest.mark.tier1
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    @pytest.mark.parametrize(
        'url',
        **parametrized(
            [
                repo.format(cred['login'], cred['pass'])
                for cred in invalid_http_credentials()
                for repo in (FAKE_5_YUM_REPO, FAKE_7_PUPPET_REPO)
            ]
        ),
    )
    def test_negative_update_auth_url_too_long(self, repo, url):
        """Update the original url for a repository to value which is too long

        :id: cc00fbf4-d284-4404-88d9-ea0c0f03abe1

        :parametrized: yes

        :expectedresults: Repository url not updated

        :CaseImportance: Critical
        """
        repo.url = url
        with pytest.raises(HTTPError):
            repo.update(['url'])

    @pytest.mark.tier2
    def test_positive_synchronize(self, repo):
        """Create a repo and sync it.

        :id: 03beb469-570d-4109-b447-9c4c0b849266

        :expectedresults: The repo has at least one RPM.

        :CaseLevel: Integration
        """
        repo.sync()
        assert repo.read().content_counts['rpm'] >= 1

    @pytest.mark.tier2
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized(
            [
                {
                    'content_type': 'yum',
                    'url': FAKE_5_YUM_REPO.format(creds['login'], creds['pass']),
                }
                for creds in valid_http_credentials(url_encoded=True)
                if creds['http_valid']
            ]
        ),
        indirect=True,
    )
    def test_positive_synchronize_auth_yum_repo(self, repo):
        """Check if secured repository can be created and synced

        :id: bc44881c-e13f-45a9-90c2-5b18c7b25454

        :parametrized: yes

        :expectedresults: Repository is created and synced

        :CaseLevel: Integration
        """
        # Verify that repo is not yet synced
        assert repo.content_counts['rpm'] == 0
        # Synchronize it
        repo.sync()
        # Verify it has finished
        assert repo.read().content_counts['rpm'] >= 1

    @pytest.mark.tier2
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized(
            [
                {
                    'content_type': 'yum',
                    'url': FAKE_5_YUM_REPO.format(creds['login'], creds['pass']),
                }
                for creds in valid_http_credentials(url_encoded=True)
                if not creds['http_valid']
            ]
        ),
        indirect=True,
    )
    def test_negative_synchronize_auth_yum_repo(self, repo):
        """Check if secured repo fails to synchronize with invalid credentials

        :id: 88361168-69b5-4239-819a-889e316e28dc

        :parametrized: yes

        :expectedresults: Repository is created but synchronization fails

        :CaseLevel: Integration
        """
        with pytest.raises(TaskFailedError):
            repo.sync()

    @pytest.mark.tier2
    @pytest.mark.upgrade
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized(
            [
                {
                    'content_type': 'puppet',
                    'url': FAKE_7_PUPPET_REPO.format(creds['login'], creds['pass']),
                }
                for creds in valid_http_credentials(url_encoded=True)
                if creds['http_valid']
            ]
        ),
        indirect=True,
    )
    def test_positive_synchronize_auth_puppet_repo(self, repo):
        """Check if secured puppet repository can be created and synced

        :id: a1e25d36-baae-46cb-aa3b-5cb9fca4f059

        :parametrized: yes

        :expectedresults: Repository is created and synced

        :CaseLevel: Integration
        """
        # Verify that repo is not yet synced
        assert repo.content_counts['puppet_module'] == 0
        # Synchronize it
        repo.sync()
        # Verify it has finished
        assert repo.read().content_counts['puppet_module'] == 1

    @pytest.mark.tier2
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized([{'content_type': 'yum', 'url': FAKE_2_YUM_REPO}]),
        indirect=True,
    )
    def test_positive_resynchronize_rpm_repo(self, repo):
        """Check that repository content is resynced after packages were
        removed from repository

        :id: a5c056ab-16c3-4052-b53d-818163b9983e

        :parametrized: yes

        :expectedresults: Repository has updated non-zero packages count

        :BZ: 1459845, 1318004

        :CaseLevel: Integration
        """
        # Synchronize it
        repo.sync()
        assert repo.read().content_counts['rpm'] >= 1
        # Find repo packages and remove them
        packages = entities.Package(repository=repo).search(query={'per_page': '1000'})
        repo.remove_content(data={'ids': [package.id for package in packages]})
        assert repo.read().content_counts['rpm'] == 0
        # Re-synchronize repository
        repo.sync()
        assert repo.read().content_counts['rpm'] >= 1

    @pytest.mark.tier2
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized([{'content_type': 'puppet', 'url': FAKE_1_PUPPET_REPO}]),
        indirect=True,
    )
    def test_positive_resynchronize_puppet_repo(self, repo):
        """Check that repository content is resynced after puppet modules
        were removed from repository

        :id: db50beb0-de73-4783-abc8-57e61188b6c7

        :parametrized: yes

        :expectedresults: Repository has updated non-zero puppet modules count

        :CaseLevel: Integration

        :BZ: 1318004
        """
        # Synchronize it
        repo.sync()
        assert repo.read().content_counts['puppet_module'] >= 1
        # Find repo packages and remove them
        modules = entities.PuppetModule(repository=[repo]).search(query={'per_page': '1000'})
        repo.remove_content(data={'ids': [module.id for module in modules]})
        assert repo.read().content_counts['puppet_module'] == 0
        # Re-synchronize repository
        repo.sync()
        assert repo.read().content_counts['puppet_module'] >= 1

    @pytest.mark.tier1
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized([{'name': name} for name in valid_data_list().values()]),
        indirect=True,
    )
    def test_positive_delete(self, repo):
        """Create a repository with different names and then delete it.

        :id: 29c2571a-b7fb-4ec7-b433-a1840758bcb0

        :parametrized: yes

        :expectedresults: The repository deleted successfully.

        :CaseImportance: Critical
        """
        repo.delete()
        with pytest.raises(HTTPError):
            repo.read()

    @pytest.mark.tier2
    @pytest.mark.upgrade
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized([{'content_type': 'yum', 'url': FAKE_2_YUM_REPO}]),
        indirect=True,
    )
    def test_positive_delete_rpm(self, repo):
        """Check if rpm repository with packages can be deleted.

        :id: d61c8c8b-2b77-4bff-b215-fa2b7c05aa78

        :parametrized: yes

        :expectedresults: The repository deleted successfully.

        :CaseLevel: Integration
        """
        repo.sync()
        # Check that there is at least one package
        assert repo.read().content_counts['rpm'] >= 1
        repo.delete()
        with pytest.raises(HTTPError):
            repo.read()

    @pytest.mark.tier2
    @pytest.mark.upgrade
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized([{'content_type': 'puppet', 'url': FAKE_1_PUPPET_REPO}]),
        indirect=True,
    )
    def test_positive_delete_puppet(self, repo):
        """Check if puppet repository with puppet modules can be deleted.

        :id: 5c60b0ab-ef50-41a3-8578-bfdb5cb228ea

        :parametrized: yes

        :expectedresults: The repository deleted successfully.

        :CaseLevel: Integration

        :BZ: 1316681
        """
        repo.sync()
        # Check that there is at least one puppet module
        assert repo.read().content_counts['puppet_module'] >= 1
        repo.delete()
        with pytest.raises(HTTPError):
            repo.read()

    @pytest.mark.tier1
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized([{'content_type': 'puppet', 'url': FAKE_0_PUPPET_REPO}]),
        indirect=True,
    )
    @pytest.mark.parametrize(
        'repo_options_2',
        **parametrized([{'content_type': 'puppet', 'url': FAKE_1_PUPPET_REPO}]),
    )
    def test_positive_list_puppet_modules_with_multiple_repos(
        self, repo, repo_options_2, module_org, module_product
    ):
        """Verify that puppet modules list for specific repo is correct
        and does not affected by other repositories.

        :id: e9e16ac2-a58d-4d49-b378-59e4f5b3a3ec

        :parametrized: yes

        :expectedresults: Number of modules has no changed after a second repo
            was synced.

        :CaseImportance: Critical
        """
        # Sync first repo
        repo.sync()
        # Verify that number of synced modules is correct
        content_count = repo.read().content_counts['puppet_module']
        modules_num = len(repo.puppet_modules()['results'])
        assert content_count == modules_num

        # Create and sync second repo
        repo_2 = entities.Repository(product=module_product, **repo_options_2).create()
        repo_2.sync()

        # Verify that number of modules from the first repo has not changed
        assert len(repo.puppet_modules()['results']) == modules_num

    @pytest.mark.tier2
    @pytest.mark.upgrade
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized([{'content_type': 'yum', 'unprotected': False, 'url': FAKE_2_YUM_REPO}]),
        indirect=True,
    )
    def test_positive_access_protected_repository(self, module_org, repo):
        """Access protected/https repository data file URL using organization
        debug certificate

        :id: 4dba5b31-1818-45dd-a9bd-3ec627c3db57

        :parametrized: yes

        :customerscenario: true

        :expectedresults: The repository data file successfully accessed.

        :BZ: 1242310

        :CaseLevel: Integration

        :CaseImportance: High
        """
        repo.sync()
        repo_data_file_url = urljoin(repo.full_path, 'repodata/repomd.xml')
        # ensure the url is based on the protected base server URL
        assert repo_data_file_url.startswith(f'https://{settings.server.hostname}')
        # try to access repository data without organization debug certificate
        with pytest.raises(SSLError):
            client.get(repo_data_file_url, verify=False)
        # get the organization debug certificate
        cert_content = module_org.download_debug_certificate()
        # save the organization debug certificate to file
        cert_file_path = f'{tempfile.gettempdir()}/{module_org.label}.pem'
        with open(cert_file_path, 'w') as cert_file:
            cert_file.write(cert_content)
        # access repository data with organization debug certificate
        response = client.get(repo_data_file_url, cert=cert_file_path, verify=False)
        assert response.status_code == 200

    @pytest.mark.tier1
    @pytest.mark.upgrade
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized(
            [{'content_type': 'yum', 'unprotected': False, 'url': CUSTOM_MODULE_STREAM_REPO_2}]
        ),
        indirect=True,
    )
    def test_module_stream_repository_crud_operations(self, repo):
        """Verify that module stream api calls works with product having other type
        repositories.

        :id: 61a5d24e-d4da-487d-b6ea-9673c05ceb60

        :parametrized: yes

        :expectedresults: module stream repo create, update, delete api calls should work with
         count of module streams

        :CaseImportance: Critical
        """
        repo.sync()
        assert repo.read().content_counts['module_stream'] == 7

        repo.url = CUSTOM_MODULE_STREAM_REPO_1
        repo = repo.update(['url'])
        repo.sync()
        assert repo.read().content_counts['module_stream'] >= 14

        repo.delete()
        with pytest.raises(HTTPError):
            repo.read()


@pytest.mark.run_in_one_thread
class TestRepositorySync:
    """Tests for ``/katello/api/repositories/:id/sync``."""

    @pytest.mark.tier2
    @skip_if_not_set('fake_manifest')
    def test_positive_sync_rh(self, module_org):
        """Sync RedHat Repository.

        :id: d69c44cd-753c-4a75-9fd5-a8ed963b5e04

        :expectedresults: Synced repo should fetch the data successfully.

        :CaseLevel: Integration
        """
        with manifests.clone() as manifest:
            upload_manifest(module_org.id, manifest.content)
        repo_id = enable_rhrepo_and_fetchid(
            basearch='x86_64',
            org_id=module_org.id,
            product=PRDS['rhel'],
            repo=REPOS['rhst7']['name'],
            reposet=REPOSET['rhst7'],
            releasever=None,
        )
        entities.Repository(id=repo_id).sync()

    @pytest.mark.tier2
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized([{'content_type': 'yum', 'url': FAKE_0_YUM_REPO_STRING_BASED_VERSIONS}]),
        indirect=True,
    )
    def test_positive_sync_yum_with_string_based_version(self, repo):
        """Sync Yum Repo with string based versions on update-info.

        :id: 22eaef61-0fd9-4db0-abd7-433e23c2686d

        :parametrized: yes

        :expectedresults: Synced repo should fetch the data successfully and
         parse versions as string.

        :CaseLevel: Integration

        :BZ: 1741011
        """
        repo.sync()
        repo = repo.read()

        for key, count in FAKE_0_YUM_REPO_STRING_BASED_VERSIONS_COUNTS.items():
            assert repo.content_counts[key] == count

    @pytest.mark.stubbed
    @pytest.mark.tier2
    @skip_if_not_set('fake_manifest')
    def test_positive_sync_rh_app_stream(self):
        """Sync RedHat Appstream Repository.

        :id: 44810877-15cd-48c4-aa85-5881b5c4410e

        :expectedresults: Synced repo should fetch the data successfully and
         it should contain the module streams.

        :CaseLevel: Integration
        """
        pass


class TestDockerRepository:
    """Tests specific to using ``Docker`` repositories."""

    @pytest.mark.tier1
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized(
            [
                {
                    'content_type': 'docker',
                    'docker_upstream_name': DOCKER_UPSTREAM_NAME,
                    'name': name,
                    'url': DOCKER_REGISTRY_HUB,
                }
                for name in valid_docker_repository_names()
            ]
        ),
        indirect=True,
    )
    def test_positive_create(self, repo_options, repo):
        """Create a Docker-type repository

        :id: 2ce5b52d-8470-4c33-aeeb-9aee1af1cd74

        :parametrized: yes

        :expectedresults: A repository is created with a Docker repository.

        :CaseImportance: Critical
        """
        for k in 'name', 'docker_upstream_name', 'content_type':
            assert getattr(repo, k) == repo_options[k]

    @pytest.mark.tier1
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized(
            [
                {
                    'content_type': 'docker',
                    'docker_upstream_name': DOCKER_UPSTREAM_NAME,
                    'name': gen_string('alphanumeric', 10),
                    'url': DOCKER_REGISTRY_HUB,
                }
            ]
        ),
        indirect=True,
    )
    def test_positive_synchronize(self, repo):
        """Create and sync a Docker-type repository

        :id: 27653663-e5a7-4700-a3c1-f6eab6468adf

        :parametrized: yes

        :expectedresults: A repository is created with a Docker repository and
            it is synchronized.

        :CaseImportance: Critical
        """
        # TODO: add timeout support to sync(). This repo needs more than the default 300 seconds.
        repo.sync()
        assert repo.read().content_counts['docker_manifest'] >= 1

    @pytest.mark.tier1
    @pytest.mark.parametrize(
        'repo_options', **parametrized([{'content_type': 'docker'}]), indirect=True
    )
    def test_positive_update_name(self, repo):
        """Update a repository's name.

        :id: 6dff0c90-170f-40b9-9347-8ec97d89f2fd

        :parametrized: yes

        :expectedresults: The repository's name is updated.

        :CaseImportance: Critical

        :BZ: 1194476
        """
        # The only data provided with the PUT request is a name. No other
        # information about the repository (such as its URL) is provided.
        new_name = gen_string('alpha')
        repo.name = new_name
        repo = repo.update(['name'])
        assert repo.name == new_name

    @pytest.mark.tier2
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized(
            [
                {
                    'content_type': 'docker',
                    'docker_upstream_name': settings.docker.private_registry_name,
                    'name': gen_string('alpha'),
                    'upstream_username': settings.docker.private_registry_username,
                    'upstream_password': settings.docker.private_registry_password,
                    'url': settings.docker.private_registry_url,
                }
            ]
        ),
        indirect=True,
    )
    def test_positive_synchronize_private_registry(self, repo):
        """Create and sync a Docker-type repository from a private registry

        :id: c71fe7c1-1160-4145-ac71-f827c14b1027

        :parametrized: yes

        :expectedresults: A repository is created with a private Docker \
            repository and it is synchronized.

        :customerscenario: true

        :BZ: 1475121

        :CaseLevel: Integration
        """
        repo.sync()
        assert repo.read().content_counts['docker_manifest'] >= 1

    @pytest.mark.tier2
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized(
            [
                {
                    'content_type': 'docker',
                    'docker_upstream_name': settings.docker.private_registry_name,
                    'name': gen_string('alpha'),
                    'upstream_username': settings.docker.private_registry_username,
                    'upstream_password': 'ThisIsaWrongPassword',
                    'url': settings.docker.private_registry_url,
                }
            ]
        ),
        indirect=True,
    )
    def test_negative_synchronize_private_registry_wrong_password(self, repo_options, repo):
        """Create and try to sync a Docker-type repository from a private
        registry providing wrong credentials the sync must fail with
        reasonable error message.

        :id: 2857fce2-fed7-49fc-be20-bf2e4726c9f5

        :parametrized: yes

        :expectedresults: A repository is created with a private Docker \
            repository and sync fails with reasonable error message.

        :customerscenario: true

        :BZ: 1475121, 1580510

        :CaseLevel: Integration
        """
        msg = (
            f'DKR1007: Could not fetch repository {repo_options["docker_upstream_name"]} from'
            f' registry {repo_options["url"]} - Unauthorized or Not Found'
        )
        with pytest.raises(TaskFailedError, match=msg):
            repo.sync()

    @pytest.mark.tier2
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized(
            [
                {
                    'content_type': 'docker',
                    'docker_upstream_name': settings.docker.private_registry_name,
                    'name': gen_string('alpha'),
                    'upstream_username': gen_string('alpha'),
                    'upstream_password': gen_string('alpha'),
                    'url': 'https://redhat.com',
                }
            ]
        ),
        indirect=True,
    )
    def test_negative_synchronize_private_registry_wrong_repo(self, repo_options, repo):
        """Create and try to sync a Docker-type repository from a private
        registry providing wrong repository the sync must fail with
        reasonable error message.

        :id: 16c21aaf-796e-4e29-b3a1-7d93de0d6257

        :parametrized: yes

        :expectedresults: A repository is created with a private Docker \
            repository and sync fails with reasonable error message.

        :customerscenario: true

        :BZ: 1475121, 1580510

        :CaseLevel: Integration
        """
        msg = f'DKR1008: Could not find registry API at {repo_options["url"]}'
        with pytest.raises(TaskFailedError, match=msg):
            repo.sync()

    @pytest.mark.tier2
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized(
            [
                {
                    'content_type': 'docker',
                    'docker_upstream_name': settings.docker.private_registry_name,
                    'name': gen_string('alpha'),
                    'upstream_username': settings.docker.private_registry_username,
                    'url': settings.docker.private_registry_url,
                }
            ]
        ),
        indirect=True,
    )
    def test_negative_synchronize_private_registry_no_passwd(self, repo_options, module_product):
        """Create and try to sync a Docker-type repository from a private
        registry providing empty password and the sync must fail with
        reasonable error message.

        :id: 86bde2f1-4761-4045-aa54-c7be7715cd3a

        :parametrized: yes

        :expectedresults: A repository is created with a private Docker \
            repository and sync fails with reasonable error message.

        :customerscenario: true

        :BZ: 1475121, 1580510

        :CaseLevel: Integration
        """
        msg = (
            '422 Client Error: Unprocessable Entity for url: '
            f'https://{settings.server.hostname}/katello/api/v2/repositories'
        )
        with pytest.raises(HTTPError, match=msg):
            entities.Repository(**repo_options).create()

    @pytest.mark.tier2
    @pytest.mark.upgrade
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized(
            [
                {
                    'content_type': 'docker',
                    'docker_tags_whitelist': ['latest'],
                    'docker_upstream_name': DOCKER_UPSTREAM_NAME,
                    'name': gen_string('alphanumeric', 10),
                    'url': DOCKER_REGISTRY_HUB,
                }
            ]
        ),
        indirect=True,
    )
    def test_positive_synchronize_docker_repo_with_tags_whitelist(self, repo_options, repo):
        """Check if only whitelisted tags are synchronized

        :id: abd584ef-f616-49d8-ab30-ae32e4e8a685

        :parametrized: yes

        :expectedresults: Only whitelisted tag is synchronized
        """
        repo.sync()
        repo = repo.read()
        assert repo.docker_tags_whitelist == repo_options['docker_tags_whitelist']
        assert repo.content_counts['docker_tag'] == 1

    @pytest.mark.tier2
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized(
            [
                {
                    'content_type': 'docker',
                    'docker_upstream_name': DOCKER_UPSTREAM_NAME,
                    'name': gen_string('alphanumeric', 10),
                    'url': DOCKER_REGISTRY_HUB,
                }
            ]
        ),
        indirect=True,
    )
    def test_positive_synchronize_docker_repo_set_tags_later(self, repo):
        """Verify that adding tags whitelist and re-syncing after
        synchronizing full repository doesn't remove content that was
        already pulled in

        :id: 6838e152-5fd9-4f25-ae04-67760571f6ba

        :parametrized: yes

        :expectedresults: Non-whitelisted tags are not removed
        """
        # TODO: add timeout support to sync(). This repo needs more than the default 300 seconds.
        repo.sync()
        repo = repo.read()
        assert len(repo.docker_tags_whitelist) == 0
        assert repo.content_counts['docker_tag'] >= 2

        tags = ['latest']
        repo.docker_tags_whitelist = tags
        repo.update(['docker_tags_whitelist'])
        repo.sync()
        repo = repo.read()

        assert repo.docker_tags_whitelist == tags
        assert repo.content_counts['docker_tag'] >= 2

    @pytest.mark.tier2
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized(
            [
                {
                    'content_type': 'docker',
                    'docker_tags_whitelist': ['latest', gen_string('alpha')],
                    'docker_upstream_name': DOCKER_UPSTREAM_NAME,
                    'name': gen_string('alphanumeric', 10),
                    'url': DOCKER_REGISTRY_HUB,
                }
            ]
        ),
        indirect=True,
    )
    def test_negative_synchronize_docker_repo_with_mix_valid_invalid_tags(
        self, repo_options, repo
    ):
        """Set tags whitelist to contain both valid and invalid (non-existing)
        tags. Check if only whitelisted tags are synchronized

        :id: 7b66171f-5bf1-443b-9ca3-9614d66a0c6b

        :parametrized: yes

        :expectedresults: Only whitelisted tag is synchronized
        """
        repo.sync()
        repo = repo.read()
        assert repo.docker_tags_whitelist == repo_options['docker_tags_whitelist']
        assert repo.content_counts['docker_tag'] == 1

    @pytest.mark.tier2
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized(
            [
                {
                    'content_type': 'docker',
                    'docker_tags_whitelist': [gen_string('alpha') for _ in range(3)],
                    'docker_upstream_name': DOCKER_UPSTREAM_NAME,
                    'name': gen_string('alphanumeric', 10),
                    'url': DOCKER_REGISTRY_HUB,
                }
            ]
        ),
        indirect=True,
    )
    def test_negative_synchronize_docker_repo_with_invalid_tags(self, repo_options, repo):
        """Set tags whitelist to contain only invalid (non-existing)
        tags. Check that no data is synchronized.

        :id: c419da6a-1530-4f66-8f8e-d4ec69633356

        :parametrized: yes

        :expectedresults: Tags are not synchronized
        """
        repo.sync()
        repo = repo.read()
        assert repo.docker_tags_whitelist == repo_options['docker_tags_whitelist']
        assert repo.content_counts['docker_tag'] == 0


class TestOstreeRepository:
    """Tests specific to using ``OSTree`` repositories."""

    @pytest.mark.tier1
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized(
            [{'content_type': 'ostree', 'unprotected': False, 'url': FEDORA27_OSTREE_REPO}]
        ),
        indirect=True,
    )
    def test_positive_create_ostree(self, repo_options, repo):
        """Create ostree repository.

        :id: f3332dd3-1e6d-44e2-8f24-fae6fba2de8d

        :parametrized: yes

        :expectedresults: A repository is created and has ostree type.

        :CaseImportance: Critical
        """
        assert repo.content_type == repo_options['content_type']

    @pytest.mark.tier1
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized(
            [{'content_type': 'ostree', 'unprotected': False, 'url': FEDORA27_OSTREE_REPO}]
        ),
        indirect=True,
    )
    def test_positive_update_name(self, repo):
        """Update ostree repository name.

        :id: 4d9f1418-cc08-4c3c-a5dd-1d20fb9052a2

        :parametrized: yes

        :expectedresults: The repository name is updated.

        :CaseImportance: Critical
        """
        new_name = gen_string('alpha')
        repo.name = new_name
        repo = repo.update(['name'])
        assert repo.name == new_name

    @pytest.mark.tier1
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized(
            [{'content_type': 'ostree', 'unprotected': False, 'url': FEDORA27_OSTREE_REPO}]
        ),
        indirect=True,
    )
    def test_positive_update_url(self, repo):
        """Update ostree repository url.

        :id: 6ba45475-a060-42a7-bc9e-ea2824a5476b

        :parametrized: yes

        :expectedresults: The repository url is updated.

        :CaseImportance: Critical
        """
        new_url = FEDORA26_OSTREE_REPO
        repo.url = new_url
        repo = repo.update(['url'])
        assert repo.url == new_url

    @pytest.mark.tier1
    @pytest.mark.upgrade
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized(
            [{'content_type': 'ostree', 'unprotected': False, 'url': FEDORA27_OSTREE_REPO}]
        ),
        indirect=True,
    )
    def test_positive_delete_ostree(self, repo):
        """Delete an ostree repository.

        :id: 05db79ed-28c7-47fc-85f5-194a805d71ca

        :parametrized: yes

        :expectedresults: The ostree repository deleted successfully.

        :CaseImportance: Critical
        """
        repo.delete()
        with pytest.raises(HTTPError):
            repo.read()

    @pytest.mark.tier2
    @pytest.mark.skip_if_open("BZ:1625783")
    @pytest.mark.run_in_one_thread
    @skip_if_not_set('fake_manifest')
    @pytest.mark.upgrade
    def test_positive_sync_rh_atomic(self, module_org):
        """Sync RH Atomic Ostree Repository.

        :id: 38c8aeaa-5ad2-40cb-b1d2-f0ac604f9fdd

        :expectedresults: Synced repo should fetch the data successfully.

        :CaseLevel: Integration

        :BZ: 1625783
        """
        with manifests.clone() as manifest:
            upload_manifest(module_org.id, manifest.content)
        repo_id = enable_rhrepo_and_fetchid(
            org_id=module_org.id,
            product=PRDS['rhah'],
            repo=REPOS['rhaht']['name'],
            reposet=REPOSET['rhaht'],
            releasever=None,
            basearch=None,
        )
        call_entity_method_with_timeout(entities.Repository(id=repo_id).sync, timeout=1500)


class TestSRPMRepository:
    """Tests specific to using repositories containing source RPMs."""

    @pytest.mark.upgrade
    @pytest.mark.tier2
    def test_positive_srpm_upload_publish_promote_cv(self, module_org, env, repo):
        """Upload SRPM to repository, add repository to content view
        and publish, promote content view

        :id: f87391c6-c18a-4c4f-81db-decbba7f1856

        :expectedresults: srpms can be listed in organization, content view, Lifecycle env
        """
        entities.ContentUpload(repository=repo).upload(
            filepath=get_data_file(SRPM_TO_UPLOAD), content_type='srpm'
        )

        cv = entities.ContentView(organization=module_org, repository=[repo]).create()
        cv.publish()
        cv = cv.read()

        assert cv.repository[0].read().content_counts['srpm'] == 1
        assert len(entities.Srpms().search(query={'organization_id': module_org.id})) >= 1

        assert (
            len(entities.Srpms().search(query={'content_view_version_id': cv.version[0].id})) == 1
        )

    @pytest.mark.upgrade
    @pytest.mark.tier2
    @pytest.mark.skip('Uses deprecated SRPM repository')
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    @pytest.mark.parametrize(
        'repo_options', **parametrized([{'url': FAKE_YUM_SRPM_REPO}]), indirect=True
    )
    def test_positive_repo_sync_publish_promote_cv(self, module_org, env, repo):
        """Synchronize repository with SRPMs, add repository to content view
        and publish, promote content view

        :id: f87381c6-c18a-4c4f-82db-decbaa7f1846

        :parametrized: yes

        :expectedresults: srpms can be listed in organization, content view, Lifecycle env
        """
        repo.sync()

        cv = entities.ContentView(organization=module_org, repository=[repo]).create()
        cv.publish()
        cv = cv.read()

        assert cv.repository[0].read().content_counts['srpm'] == 3
        assert len(entities.Srpms().search(query={'organization_id': module_org.id})) >= 3

        assert (
            len(entities.Srpms().search(query={'content_view_version_id': cv.version[0].id})) >= 3
        )

        promote(cv.version[0], env.id)
        assert len(entities.Srpms().search(query={'environment_id': env.id})) == 3


@pytest.mark.skip_if_open('BZ:1682951')
class TestDRPMRepository:
    """Tests specific to using repositories containing delta RPMs."""

    @pytest.mark.tier2
    @pytest.mark.skip('Uses deprecated DRPM repository')
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    @pytest.mark.parametrize(
        'repo_options', **parametrized([{'url': FAKE_YUM_DRPM_REPO}]), indirect=True
    )
    def test_positive_sync(self, module_org, module_product, repo):
        """Synchronize repository with DRPMs

        :id: 7816031c-b7df-49e0-bf42-7f6e2d9b0233

        :parametrized: yes

        :expectedresults: drpms can be listed in repository
        """
        repo.sync()
        result = ssh.command(
            'ls /var/lib/pulp/published/yum/https/repos/{}/Library'
            '/custom/{}/{}/drpms/ | grep .drpm'.format(
                module_org.label, module_product.label, repo.label
            )
        )
        assert result.return_code == 0
        assert len(result.stdout) >= 1

    @pytest.mark.tier2
    @pytest.mark.skip('Uses deprecated DRPM repository')
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    @pytest.mark.parametrize(
        'repo_options', **parametrized([{'url': FAKE_YUM_DRPM_REPO}]), indirect=True
    )
    def test_positive_sync_publish_cv(self, module_org, module_product, repo):
        """Synchronize repository with DRPMs, add repository to content view
        and publish content view

        :id: dac4bd82-1433-4e5d-b82f-856056ca3924

        :parametrized: yes

        :expectedresults: drpms can be listed in content view
        """
        repo.sync()

        cv = entities.ContentView(organization=module_org, repository=[repo]).create()
        cv.publish()

        result = ssh.command(
            'ls /var/lib/pulp/published/yum/https/repos/{}/content_views/{}'
            '/1.0/custom/{}/{}/drpms/ | grep .drpm'.format(
                module_org.label, cv.label, module_product.label, repo.label
            )
        )
        assert result.return_code == 0
        assert len(result.stdout) >= 1

    @pytest.mark.tier2
    @pytest.mark.upgrade
    @pytest.mark.skip('Uses deprecated DRPM repository')
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    @pytest.mark.parametrize(
        'repo_options', **parametrized([{'url': FAKE_YUM_DRPM_REPO}]), indirect=True
    )
    def test_positive_sync_publish_promote_cv(self, module_org, env, module_product, repo):
        """Synchronize repository with DRPMs, add repository to content view,
        publish and promote content view to lifecycle environment

        :id: 44296354-8ca2-4ce0-aa16-398effc80d9c

        :parametrized: yes

        :expectedresults: drpms can be listed in content view in proper
            lifecycle environment
        """
        repo.sync()
        cv = entities.ContentView(organization=module_org, repository=repo).create()
        cv.publish()
        cv = cv.read()

        promote(cv.version[0], env.id)
        result = ssh.command(
            'ls /var/lib/pulp/published/yum/https/repos/{}/{}/{}/custom/{}/{}'
            '/drpms/ | grep .drpm'.format(
                module_org.label, env.name, cv.label, module_product.label, repo.label
            )
        )
        assert result.return_code == 0
        assert len(result.stdout) >= 1


class TestSRPMRepositoryIgnoreContent:
    """Test whether SRPM content can be ignored during sync.

    In particular sync of duplicate SRPMs would fail when using the flag
    ``ignorable_content``.

    :CaseLevel: Integration

    :CaseComponent: Pulp

    :BZ: 1673215
    """

    @pytest.mark.tier2
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized([{'ignorable_content': ['srpm'], 'url': FAKE_YUM_SRPM_REPO}]),
        indirect=True,
    )
    def test_positive_ignore_srpm_duplicate(self, repo):
        """Test whether SRPM duplicated content can be ignored.

        :id: de03aaa1-1f95-4c28-9f53-362ceb113167

        :parametrized: yes

        :expectedresults: SRPM content is ignored during sync.
        """
        repo.sync()
        repo = repo.read()
        assert repo.content_counts['srpm'] == 0

    @pytest.mark.tier2
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    @pytest.mark.parametrize(
        'repo_options', **parametrized([{'url': FAKE_YUM_SRPM_DUPLICATE_REPO}]), indirect=True
    )
    def test_positive_sync_srpm_duplicate(self, repo):
        """Test sync of SRPM duplicated repository.

        :id: 83749adc-0561-44c9-8710-eec600704dde

        :parametrized: yes

        :expectedresults: SRPM content is not ignored during the sync. No
            exceptions to be raised.
        """
        repo.sync()
        repo = repo.read()
        assert repo.content_counts['srpm'] == 2

    @pytest.mark.tier2
    @pytest.mark.skip('Uses deprecated SRPM repository')
    @pytest.mark.skipif((not settings.repos_hosting_url), reason='Missing repos_hosting_url')
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized([{'ignorable_content': ['srpm'], 'url': FAKE_YUM_SRPM_REPO}]),
        indirect=True,
    )
    def test_positive_ignore_srpm_sync(self, repo):
        """Test whether SRPM content can be ignored during sync.

        :id: a2aeb307-00b2-42fe-a682-4b09474f389f

        :parametrized: yes

        :expectedresults: SRPM content is ignore during the sync.
        """
        repo.sync()
        repo = repo.read()
        assert repo.content_counts['srpm'] == 0
        assert repo.content_counts['erratum'] == 2


class TestFileRepository:
    """Specific tests for File Repositories"""

    @pytest.mark.stubbed
    @pytest.mark.tier1
    def test_positive_upload_file_to_file_repo(self):
        """Check arbitrary file can be uploaded to File Repository

        :id: fdb46481-f0f4-45aa-b075-2a8f6725e51b

        :Steps:
            1. Create a File Repository
            2. Upload an arbitrary file to it

        :expectedresults: uploaded file is available under File Repository

        :CaseImportance: Critical

        :CaseAutomation: NotAutomated
        """
        pass

    @pytest.mark.stubbed
    @pytest.mark.tier1
    def test_positive_file_permissions(self):
        """Check file permissions after file upload to File Repository

        :id: 03b4b7dd-0505-4302-ae00-5de33ad420b0

        :Setup:
            1. Create a File Repository
            2. Upload an arbitrary file to it

        :Steps: Retrieve file permissions from File Repository

        :expectedresults: uploaded file permissions are kept after upload

        :CaseImportance: Critical

        :CaseAutomation: NotAutomated
        """
        pass

    @pytest.mark.stubbed
    @pytest.mark.tier1
    @pytest.mark.upgrade
    def test_positive_remove_file(self):
        """Check arbitrary file can be removed from File Repository

        :id: 65068b4c-9018-4baa-b87b-b6e9d7384a5d

        :Setup:
            1. Create a File Repository
            2. Upload an arbitrary file to it

        :Steps: Remove a file from File Repository

        :expectedresults: file is not listed under File Repository after
            removal

        :CaseImportance: Critical

        :CaseAutomation: NotAutomated
        """
        pass

    @pytest.mark.stubbed
    @pytest.mark.tier2
    @pytest.mark.upgrade
    def test_positive_remote_directory_sync(self):
        """Check an entire remote directory can be synced to File Repository
        through http

        :id: 5c29b758-004a-4c71-a860-7087a0e96747

        :Setup:
            1. Create a directory to be synced with a pulp manifest on its root
            2. Make the directory available through http

        :Steps:
            1. Create a File Repository with url pointing to http url
                created on setup
            2. Initialize synchronization


        :expectedresults: entire directory is synced over http

        :CaseAutomation: NotAutomated
        """
        pass

    @pytest.mark.stubbed
    @pytest.mark.tier1
    def test_positive_local_directory_sync(self):
        """Check an entire local directory can be synced to File Repository

        :id: 178145e6-62e1-4cb9-b825-44d3ab41e754

        :Setup:
            1. Create a directory to be synced with a pulp manifest on its root
                locally (on the Satellite/Foreman host)

        :Steps:
            1. Create a File Repository with url pointing to local url
                created on setup
            2. Initialize synchronization


        :expectedresults: entire directory is synced

        :CaseImportance: Critical

        :CaseAutomation: NotAutomated
        """
        pass

    @pytest.mark.stubbed
    @pytest.mark.tier1
    def test_positive_symlinks_sync(self):
        """Check synlinks can be synced to File Repository

        :id: 438a8e21-3502-4995-86db-c67ba0f3c469

        :Setup:
            1. Create a directory to be synced with a pulp manifest on its root
                locally (on the Satellite/Foreman host)
            2. Make sure it contains synlinks

        :Steps:
            1. Create a File Repository with url pointing to local url
                created on setup
            2. Initialize synchronization

        :expectedresults: entire directory is synced, including files
            referred by symlinks

        :CaseImportance: Critical

        :CaseAutomation: NotAutomated
        """
        pass


class TestTokenAuthContainerRepository:
    """These test are similar to the ones in ``TestDockerRepository``,
    but test with more container registries and registries that use
    really long (>255 or >1024) tokens for passwords.
    These test require container registry configs in the
    container_repo section of robottelo.yaml

    :CaseComponent: ContainerManagement-Content
    """

    @pytest.mark.skipif(
        (not settings.container_repo.long_pass_registry), reason='long_pass_registry not set'
    )
    @pytest.mark.tier2
    @pytest.mark.parametrize(
        'repo_options',
        **parametrized(
            [
                {
                    'content_type': 'docker',
                    'docker_upstream_name': name,
                    'name': gen_string('alpha'),
                    'upstream_username': settings.container_repo.long_pass_registry[
                        'registry_username'
                    ],
                    'upstream_password': settings.container_repo.long_pass_registry[
                        'registry_password'
                    ],
                    'url': settings.container_repo.long_pass_registry['registry_url'],
                }
                for name in settings.container_repo.long_pass_registry['repos_to_sync']
            ]
            if settings.container_repo.long_pass_registry
            else [None]
        ),
        indirect=True,
    )
    def test_positive_create_with_long_token(self, repo_options, repo):
        """Create and sync Docker-type repo from the Red Hat Container registry
        Using token based auth, with very long tokens (>255 characters).

        :id: 79ce54cd-6353-457f-a6d1-08162a1bbe1d

        :parametrized: yes

        :expectedresults: repo from registry with long password can be created
         and synced
        """
        # First we want to confirm the provided token is > 255 charaters
        assert (
            len(repo_options['upstream_password']) > 255
        ), 'Use a longer (>255) token for long_pass_test_registry'

        for k in 'name', 'docker_upstream_name', 'content_type', 'upstream_username':
            assert getattr(repo, k) == repo_options[k]
        repo.sync()
        assert repo.read().content_counts['docker_manifest'] > 1

    @pytest.mark.skipif(
        (not settings.container_repo.multi_registry_test_configs),
        reason='multi_registry_test_config not set',
    )
    @pytest.mark.tier2
    @pytest.mark.parametrize(
        'repo_options_multi',
        **parametrized(
            [
                [
                    {
                        'content_type': 'docker',
                        'docker_tags_whitelist': ['latest'],
                        'docker_upstream_name': name,
                        'name': gen_string('alpha'),
                        'upstream_username': config['registry_username'],
                        'upstream_password': config['registry_password'],
                        'url': config['registry_url'],
                    }
                    for config in settings.container_repo.multi_registry_test_configs
                    for name in config['repos_to_sync']
                ]
                if settings.container_repo.multi_registry_test_configs
                else None
            ]
        ),
    )
    def test_positive_multi_registry(self, repo_options_multi, module_org, module_product):
        """Create and sync Docker-type repos from multiple supported registries

        :id: 4f8ea85b-4c69-4da6-a8ef-bd467ee35147

        :parametrized: yes

        :expectedresults: multiple products and repos are created
        """
        for options in repo_options_multi:
            repo = entities.Repository(product=module_product, **options).create()
            for k in 'name', 'docker_upstream_name', 'content_type', 'upstream_username':
                assert getattr(repo, k) == options[k]
            repo.sync()
            assert repo.read().content_counts['docker_manifest'] >= 1
