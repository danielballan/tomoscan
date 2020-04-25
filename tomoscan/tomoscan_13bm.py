from epics import PV
from tomoscan import tomoscan
import time
import math

class tomoscan_13bm(tomoscan):

    def __init__(self, pvFile, macros=[]):
        super().__init__(pvFile, macros)
        
        # Set the detector running in FreeRun mode
        self.setTriggerMode('FreeRun', 1)
        # Enable auto-increment on file writer
        self.epicsPVs['FPAutoIncrement'].put('Yes')
        # Set the SIS output pulse width to 100 us
        self.epicsPVs['MCSLNEOutputWidth'].put(0.0001)
        
    def setTriggerMode(self, triggerMode, numImages):
        if (triggerMode == 'FreeRun'):
            self.epicsPVs['CamImageMode'].put('Continuous', wait=True)
            self.epicsPVs['CamTriggerMode'].put('Off', wait=True)
            self.epicsPVs['CamExposureMode'].put('Timed', wait=True)
            self.epicsPVs['CamAcquire'].put('Acquire')
        else: # set camera to external triggering
            self.epicsPVs['CamImageMode'].put('Multiple', wait=True)
            self.epicsPVs['CamNumImages'].put(numImages, wait=True)
            self.epicsPVs['CamTriggerMode'].put('On', wait=True)
            self.epicsPVs['CamExposureMode'].put('Timed', wait=True)
            self.epicsPVs['CamTriggerOverlap'].put('ReadOut', wait=True)
            # Set number of MCS channels, NumImages, and NumCapture
            self.epicsPVs['MCSStopAll'].put(1, wait=True)
            self.epicsPVs['MCSNuseAll'].put(numImages, wait=True)
            self.epicsPVs['FPNumCapture'].put(numImages, wait=True)
  
        if (triggerMode == 'MCSExternal'):
            # Put MCS in external trigger mode
            self.epicsPVs['MCSChannelAdvance'].put('External', wait=True)
  
        if (triggerMode == 'MCSInternal'):
            self.epicsPVs['MCSChannelAdvance'].put('Internal', wait=True)
            time = self.computeFrameTime()
            self.epicsPVs['MCSDwell'].put(time, wait=True)

    def collectNFrames(self, numFrames, save=True):
        # This is called when collecting dark fields or flat fields
        self.setTriggerMode('MCSInternal', numFrames)
        if (save):
            self.epicsPVs['FPCapture'].put('Capture')
        self.epicsPVs['CamAcquire'].put('Acquire')
        # Wait for detector and file plugin to be ready
        time.sleep(0.5)
        # Start the MCS
        self.epicsPVs['MCSEraseStart'].put(1)
        collectionTime = self.epicsPVs['MCSDwell'].value * numFrames
        self.waitCameraDone(collectionTime + 5.0)
       
    def beginScan(self):
        # Call the base class method
        super().beginScan()
        # Need to collect 3 dummy frames after changing camera to triggered mode
        self.collectNFrames(3, False)
        # The MCS LNE output stays low after stopping MCS for up to the exposure time = LNE output width
        # Need to wait for the exposure time
        time.sleep(self.epicsPVs['ExposureTime'].value)

    def endScan(self):
        # Save the configuration
        filePath = self.epicsPVs['FilePath'].get(as_string=True)
        fileName = self.epicsPVs['FileName'].get(as_string=True)
        self.saveConfiguration(filePath + fileName + '.config')
        # Put the camera back in FreeRun mode and acquiring
        self.setTriggerMode('FreeRun', 1)
        # Set the rotation speed to maximum
        maxSpeed = self.epicsPVs['RotationMaxSpeed'].value
        self.epicsPVs['RotationSpeed'].put(maxSpeed)
        # Move the sample in.  Could be out if scan was aborted while taking flat fields
        self.moveSampleIn()
        # Call the base class method
        super().endScan()

    def collectDarkFields(self):
        self.epicsPVs['ScanStatus'].put('Collecting dark fields')
        self.collectNFrames(self.epicsPVs['NumDarkFields'].value)

    def collectFlatFields(self):
        self.epicsPVs['ScanStatus'].put('Collecting flat fields')
        self.collectNFrames(self.epicsPVs['NumFlatFields'].value)
      
    def collectProjections(self):
        self.epicsPVs['ScanStatus'].put('Collecting projections')
        rotationStart = self.epicsPVs['RotationStart'].value
        rotationStep = self.epicsPVs['RotationStep'].value
        numAngles = self.epicsPVs['NumAngles'].value
        rotationStop = rotationStart + (rotationStep * numAngles)
        maxSpeed = self.epicsPVs['RotationMaxSpeed'].value
        self.epicsPVs['RotationSpeed'].put(maxSpeed)
        # Start angle is decremented a half rotation step so scan is centered on rotationStart
        # The SIS does not put out pulses until after one dwell period so need to back up an additional angle step
        self.epicsPVs['Rotation'].put((rotationStart - 1.5 * rotationStep), wait=True)
        # Compute and set the motor speed
        timePerAngle = self.computeFrameTime()
        speed = rotationStep / timePerAngle
        stepsPerDeg = abs(round(1./self.epicsPVs['RotationResolution'].value, 0))
        motorSpeed = math.floor((speed * stepsPerDeg)) / stepsPerDeg
        self.epicsPVs['RotationSpeed'].put(motorSpeed)
        # Set the external prescale according to the step size, use motor resolution steps per degree (user unit)
        self.epicsPVs['MCSStopAll'].put(1, wait=True)
        prescale = math.floor(abs(rotationStep  * stepsPerDeg))
        self.epicsPVs['MCSPrescale'].put(prescale, wait=True)
        self.setTriggerMode('MCSExternal', numAngles)
        # Start capturing in file plugin
        self.epicsPVs['FPCapture'].put('Capture')
        # Start the camera
        self.epicsPVs['CamAcquire'].put('Acquire')
        # Start the MCS
        self.epicsPVs['MCSEraseStart'].put(1)
        # Wait for detector, file plugin, and MCS to be ready
        time.sleep(0.5)
        # Start the rotation motor
        self.epicsPVs['Rotation'].put(rotationStop)
        collectionTime = numAngles * timePerAngle
        self.waitCameraDone(collectionTime + 60.)
