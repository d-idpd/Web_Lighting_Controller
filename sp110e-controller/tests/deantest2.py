from SP110E.ControllerSync import ControllerSync
#from sp110e.ControllerSync import ControllerSync

device = ControllerSync()
device.connect("CA:AC:02:04:32:24")
device.switch_on()
device.set_color([255, 0, 0])
device.set_brightness(255)