from glob import glob
from setuptools import find_packages, setup

package_name = 'tinylidarnet_ros'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', glob('launch/*.launch.py')),
        ('share/' + package_name + '/config', glob('config/*.yaml')),
    ],
    # tinylidarnetとPyTorchは車載環境に合うものを別途導入する。
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Project maintainer',
    maintainer_email='maintainer@example.com',
    description='TinyLidarNet inference and rosbag dataset conversion.',
    license='Proprietary',
    entry_points={'console_scripts': [
        'tinylidarnet_node = tinylidarnet_ros.node:main',
        'bag_to_dataset = tinylidarnet_ros.bag_to_dataset:main',
    ]},
)
