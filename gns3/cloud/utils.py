from PyQt4.QtCore import QThread
from PyQt4.QtCore import pyqtSignal

from .rackspace_ctrl import RackspaceCtrl

import paramiko

from contextlib import contextmanager
import io
from socket import error as socket_error
import logging
log = logging.getLogger(__name__)


class AllowAndForgetPolicy(paramiko.MissingHostKeyPolicy):
    """
    Custom policy for server host keys: we simply accept the key
    the server sent to us without storing it.
    """
    def missing_host_key(self, *args, **kwargs):
        """
        According to MissingHostKeyPolicy protocol, to accept
        the key, simply return.
        """
        return


@contextmanager
def ssh_client(host, key_string):
    """
    Context manager wrapping a SSHClient instance: the client connects on
    enter and close the connection on exit
    """
    client = paramiko.SSHClient()
    try:
        f_key = io.StringIO(key_string)
        key = paramiko.RSAKey.from_private_key(f_key)
        client.set_missing_host_key_policy(AllowAndForgetPolicy())
        client.connect(hostname=host, username="root", pkey=key)
        yield client
    except socket_error as e:
        log.error("SSH connection error to {}: {}".format(host, e))
        yield None
    finally:
        client.close()


def get_provider(cloud_settings):
    """
    Utility function to retrieve a cloud provider instance already authenticated and with the
    region set

    :param cloud_settings: cloud settings dictionary
    :return: a provider instance or None on errors
    """
    try:
        username = cloud_settings['cloud_user_name']
        apikey = cloud_settings['cloud_api_key']
        region = cloud_settings['cloud_region']
        ias_url = cloud_settings['gns3_ias_url']
    except KeyError as e:
        log.error("Unable to create cloud provider: {}".format(e))
        return

    provider = RackspaceCtrl(username, apikey, ias_url)

    if not provider.authenticate():
        log.error("Authentication failed for cloud provider")
        return

    if not region:
        region = provider.list_regions().values()[0]

    if not provider.set_region(region):
        log.error("Unable to set cloud provider region")
        return

    return provider


class ListInstancesThread(QThread):
    """
    Helper class to retrieve data from the provider in a separate thread,
    avoid freezing the gui
    """
    instancesReady = pyqtSignal(object)

    def __init__(self, parent, provider):
        super(QThread, self).__init__(parent)
        self._provider = provider

    def run(self):
        try:
            instances = self._provider.list_instances()
            log.info('Instance list:')
            for instance in instances:
                log.info('  {}, {}'.format(instance.name, instance.state))
            self.instancesReady.emit(instances)
        except Exception as e:
            log.error('list_instances error: {}'.format(e))


class CreateInstanceThread(QThread):
    """
    Helper class to create instances in a separate thread
    """
    instanceCreated = pyqtSignal(object, object)

    def __init__(self, parent, provider, name, flavor_id, image_id):
        super(QThread, self).__init__(parent)
        self._provider = provider
        self._name = name
        self._flavor_id = flavor_id
        self._image_id = image_id

    def run(self):
        k = self._provider.create_key_pair(self._name)
        i = self._provider.create_instance(self._name, self._flavor_id, self._image_id, k)
        self.instanceCreated.emit(i, k)


class DeleteInstanceThread(QThread):
    """
    Helper class to remove an instance in a separate thread
    """
    instanceDeleted = pyqtSignal(object)

    def __init__(self, parent, provider, instance):
        super(QThread, self).__init__(parent)
        self._provider = provider
        self._instance = instance

    def run(self):
        if self._provider.delete_instance(self._instance):
            self.instanceDeleted.emit(self._instance)


class StartGNS3ServerThread(QThread):
    """
    Perform an SSH connection to the instances in a separate thread,
    outside the GUI event loop, and start GNS3 server
    """
    gns3server_started = pyqtSignal(str, str)

    def __init__(self, parent, host, private_key_string, id, username, api_key, region, dead_time):
        super(QThread, self).__init__(parent)
        self._host = host
        self._private_key_string = private_key_string
        self._id = id
        self._username = username
        self._api_key = api_key
        self._region = region
        self._dead_time = dead_time
        log.error('got here 6 {}'.format(self._host))
        log.error('got here 6 {}'.format(self._private_key_string))
        log.error('got here 6 {}'.format(self._id))
        log.error('got here 6 {}'.format(self._username))
        log.error('got here 6 {}'.format(self._api_key))
        log.error('got here 6 {}'.format(self._region))
        log.error('got here 6 {}'.format(self._dead_time))
        log.error('got here 7')

    def run(self):
        with ssh_client(self._host, self._private_key_string) as client:
            if client is not None:
                data = {
                    'instance_id': self._id,
                    'cloud_user_name': self._username,
                    'cloud_api_key': self._api_key,
                    'region': self._region,
                    'dead_time': self._dead_time,
                }
                # TODO: Properly escape the data portion of the command line
                start_cmd = '/usr/bin/python3 /opt/gns3/gns3-server/gns3server/start_server.py -d -v --data="{}" 2>/tmp/gns3_stderr.log'.format(data)
                log.error(start_cmd)
                stdin, stdout, stderr = client.exec_command(start_cmd)
                log.info("ssh response: {}".format(stdout.read()))
                response = stdout.read()
                line = response.split('\n')[0]
                result = ast.literal_eval(line)
                result['host'] = self._host
                # TODO: have the server return the port it is running on
                result['port'] = 8000

                # emit signal on success
                self.gns3server_started.emit(self._id, result)


class WSConnectThread(QThread):
    """
    Establish websocket connection with the remote gns3server
    instance. Run outside the GUI event loop

    TODO: fix constructor parameters list
    """
    established = pyqtSignal(str)

    def __init__(self, parent, id, *args, **kwargs):
        super(QThread, self).__init__(parent)
        self._id = id
        self._host = kwargs.get('host')
        self._port = kwargs.get('port')
        self._ca_file = kwargs.get('ca_file')

    def run(self):
        """
        TODO: connect to WSS server
        """
        log.info("WSConnectThread running...")
        servers.getRemoteServer(self._host, self._port, self._ca_file)
        self.established.emit(self._id)
