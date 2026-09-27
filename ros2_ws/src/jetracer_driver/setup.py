from setuptools import find_packages, setup

package_name = 'jetracer_driver'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Project maintainer',
    maintainer_email='maintainer@example.com',
    description='JetRacer actuator driver with a reception watchdog.',
    license='Proprietary',
    entry_points={'console_scripts': ['jetracer_node = jetracer_driver.node:main']},
)
