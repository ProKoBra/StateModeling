# This example is written for the new interface
# This is the full COVID-19 model to be fitted to the RKI data
# see the PPT for details of the model design

import StateModeling as stm
import numpy as np
import matplotlib.pyplot as plt
import fetch_data
import pandas as pd
import tensorflow as tf

basePath = r"C:\Users\pi96doc\Documents\Programming\PythonScripts\StateModeling"
if False:
    data = fetch_data.DataFetcher().fetch_german_data()
    data_np = data.to_numpy()
    df = pd.read_excel(basePath + r"\Examples\bev_lk.xlsx")  # support information about the population
    RawMeasDetected, RawMeasDead, RawMeasCured, SupportingInfo = stm.cumulate(data, df)
    np.save(basePath + r'\Data\MeasDetected', RawMeasDetected)
    np.save(basePath + r'\Data\MeasDead', RawMeasDead)
    np.save(basePath + r'\Data\MeasCured', RawMeasCured)
    np.save(basePath + r'\Data\SupportingInfo', SupportingInfo)
else:
    RawMeasDetected = np.load(basePath + r'\Data\MeasDetected.npy')
    RawMeasDead = np.load(basePath + r'\Data\MeasDead.npy')
    RawMeasCured = np.load(basePath + r'\Data\MeasCured.npy')
    SupportingInfo = np.load(basePath + r'\Data\SupportingInfo.npy', allow_pickle=True)
(RawIDs, LKs, RawPopM, RawPopW, Area, Ages, Gender, Dates) = SupportingInfo

# fit,data = stm.DataLoader().get_new_data()
# axes = data.keys()
# datp = data.pivot_table(values=['cases','deaths'], index=['id','day'], aggfunc=np.sum, fill_value=0)
# data_np = datp.to_numpy()
# NumIDs = data['id'].unique().shape
# NumDays = data['day'].unique().shape

ReduceDistricts = True
if ReduceDistricts:
    # DistrictStride = 50
    # SelectedIDs = slice(0,MeasDetected.shape[1],DistrictStride)
    # IDLabels = LKs[SelectedIDs]
    SelectedIDs = (0, 200, 250, 300, 339, 340, 341, 342)  # LKs.index('SK Jena')
    # SelectedIDs = (0, 200)
    IDLabels = [LKs[index] for index in SelectedIDs]
    SelectedAges = slice(0, RawMeasDetected.shape[2] - 1)  # remove the "unknown" part
    AgeLabels = Ages[SelectedAges]
    SelectedGender = slice(0, 2)  # remove the "unknown" part
    GenderLabels = Gender[SelectedAges]
    MeasDetected = RawMeasDetected[:, SelectedIDs, SelectedAges, SelectedGender]
    MeasDead = RawMeasDead[:, SelectedIDs, SelectedAges, SelectedGender]
    PopM = [RawPopM[index] for index in SelectedIDs]  # PopM[0:-1:DistrictStride]
    PopW = [RawPopW[index] for index in SelectedIDs]  # PopW[0:-1:DistrictStride]
    IDs = [RawIDs[index] for index in SelectedIDs]  # IDs[0:-1:DistrictStride]
else:
    IDLabels = LKs
    MeasDetected = RawMeasDetected
    MeasDead = RawMeasDead
    AgeLabels = Ages
    GenderLabels = Gender
    MeasDetected = RawMeasDetected
    MeasDead = RawMeasDead
    PopM = RawPopM
    PopW = RawPopW
    IDs = RawIDs
Tmax = 120

M = stm.Model()
M.addAxis("Gender", entries=len(GenderLabels) - 1, labels=GenderLabels)
M.addAxis("Age", entries=len(AgeLabels), labels=AgeLabels)
M.addAxis("District", entries=len(IDLabels), labels=IDLabels)
M.addAxis("Disease Progression", entries=20, queue=True)
M.addAxis("Quarantine", entries=18, queue=True)

Pop = 1e6 * np.array([(3.88 + 0.78), 6.62, 2.31 + 2.59 + 3.72 + 15.84, 23.9, 15.49, 7.88], stm.CalcFloatStr)
AgeDist = (Pop / np.sum(Pop))

InitAge = M.Axes['Age'].init(AgeDist)

PopSum = np.sum(PopM) + np.sum(PopW)

InitPopulM = M.Axes['District'].init(PopM / PopSum)
InitPopulW = M.Axes['District'].init(PopW / PopSum)
InitPopul = InitAge * np.concatenate((InitPopulM, InitPopulW), -1)

# InitGender = [MRatio, 1 - MRatio]
# MRatio = np.sum(PopM) / PopSum

# susceptible
M.newState(name='S', axesInit={"Age": 1.0, "District": InitPopul, "Gender": 1.0})
# I0 = M.newVariables({'I0': 0.000055 * InitPopulM}, forcePos=False)  # a district dependent variable of initially infected
# assume 4.0 infected at time 0
#  (2.0/323299.0) * InitPopul
I0 = M.newVariables({'I0': 3.5e-7}, forcePos=False)  # a global variable of initial infection probability
# InitProgression = lambda: I0 * M.Axes['Disease Progression'].initDelta()  # variables to fit have to always be packed in lambda functions!
# M.newState(name='I', axesInit={"Disease Progression": InitProgression, "District": None, "Age": None, "Gender": None})
# infected (not detected):
M.newState(name='I', axesInit={"Disease Progression": 0, "District": 0, "Age": 0, "Gender": 0})
# cured (not detected):
M.newState(name='C', axesInit={"District": 0, "Age": 0, "Gender": 0})
T0 = M.newVariables({"T0": 14.0 * np.ones(M.Axes['District'].shape, stm.CalcFloatStr)}, forcePos=False)  # time at which a delta is injected into the start of the progression axis
# the initial infection is generated by "injecting" a Gaussian (to be differentiable)
M.addRate('S', 'I', lambda t: I0() * M.initGaussianT0(T0(), t), queueDst='Disease Progression', hasTime=True)
# Age-dependent base rate of infection
r0 = M.newVariables({'r0': 2.55 * np.ones(M.Axes['Age'].shape, stm.CalcFloatStr)}, forcePos=True)
aT0 = M.newVariables({'aT0': 65.0}, forcePos=True)  # awarenessTime
aSigma = 4.0
aBase = M.newVariables({'aBase': 0.5}, forcePos=True)  # residual relative rate after awareness effect
awareness = lambda t: M.initSigmoidDropT0(aT0(), t, aSigma, aBase())  # 40% drop in infection rate
it0 = M.newVariables({'it0': 3.5}, forcePos=True) # day of most probably infection
sigmaI = 3.0
infectiveness = M.Axes['Disease Progression'].initGaussian(it0(), sigmaI)
InitPupulDistrictOnly = np.sum(InitPopul,(-1,-2), keepdims=True)
M.addRate(('S', 'I'), 'I', lambda t: (r0()* awareness(t) * infectiveness) / InitPupulDistrictOnly,
          queueDst="Disease Progression", hasTime=True, hoSumDims=['Age', 'Gender'])  # S ==> I[0]
M.addRate('I', 'C', 1.0, queueSrc="Disease Progression")  # I --> C when through the queue

# --- The (undetected) quarantine process:
# susceptible, quarantined
M.newState(name='Sq', axesInit={"Age": 0, "Quarantine": 0, "District": 0, "Gender": 0})
# infected, quarantined
M.newState(name='Iq', axesInit={"Age": 0, "Disease Progression": 0, "District": 0, "Gender": 0})
q = M.newVariables({"q": 0.25}, forcePos=True)  # quarantine ratio (of all ppl.) modeled as a Gaussian (see below)
LockDown = 83
sigmaQ = 1.0
lockDownFct = lambda t: q() * M.initGaussianT0(LockDown, t, sigmaQ)
M.addRate('S', 'Sq', lockDownFct, queueDst='Quarantine', hasTime=True)
# M.addRate('S', 'Sq', q, queueDst="Quarantine")  # S -q-> Sq
M.addRate('Sq', 'S', 1.0, queueSrc="Quarantine")  # Sq --> S
M.addRate('I', 'Iq', lockDownFct, hasTime=True)  # S -q-> Sq
M.addRate('Iq', 'C', 1.0, queueSrc="Disease Progression")  # Iq --> C when through the infection queue. Quarantine does not matter any more
# ---------- detecting some of the infected:
# detected quarantine state:
M.newState(name='Q', axesInit={"Age": 0, "Disease Progression": 0, "District": 0, "Gender": 0})  # no quarantine axis is needed, since the desease progression takes care of this
d = M.newVariables({'d': 0.026}, forcePos=True)  # detection rate
M.addRate('I', 'Q', d)  # S -q-> Sq
M.addRate('Iq', 'Q', d)  # detection by testing inside the quarantine
# ---- hospitalizing the ill
# hospitalized state:
M.newState(name='H', axesInit={"Disease Progression": 0, "District": 0, "Age": 0, "Gender": 0})
ht0 = M.newVariables({'ht0': 5.5}, forcePos=False)  # most probable time of hospitalization
h = M.newVariables({'h': 0.12})  # rate of hospitalization, should be age dependent
# influx = M.newVariables({'influx': 0.0001})  # a district dependent variable of initially infected
# infectionRate = lambda I: (I + influx) * M.Var['r0']
AgeBorder = M.newVariables({'AgeBorder': 2.3}, forcePos=False, normalize=None)  # rate of hospitalization, should be age dependent
AgeSigma = M.newVariables({'AgeSigma': 0.5}, forcePos=False, normalize=None)  # rate of hospitalization, should be age dependent
hospitalization = lambda: h() * M.Axes['Disease Progression'].initGaussian(ht0(), 3.0) * \
                          M.Axes['Age'].initSigmoid(AgeBorder(), AgeSigma())
M.addRate('I', 'H', hospitalization)  # I[t] -> H[t]
M.addRate('Q', 'H', hospitalization)  # Q[t] -> H[t]
M.addRate('Iq', 'H', hospitalization)  # Iq[t] -> H[t]
# cured (detected):
M.newState(name='CR', axesInit={"District": 0, "Age": 0, "Gender": 0})
M.addRate('H', 'CR', 1.0, queueSrc="Disease Progression")  # H[t] -> CR[t]  this is a dequeueing operation and thus the rate needs to be one!
M.addRate('Q', 'CR', 1.0, queueSrc="Disease Progression")  # H[t] -> R[t]  this is a dequeueing operation and thus the rate needs to be one!
# ---- intensive care:
# in intensive care
M.newState(name='HIC', axesInit={"Disease Progression": 0, "District": 0, "Age": 0, "Gender": 0})
# dead
M.newState(name='D', axesInit={"District": 0, "Age": 0, "Gender": 0})
hic = 0.05  # should be age dependent
M.addRate('H', 'HIC', hic)
M.addRate('HIC', 'H', 1.0, queueSrc="Disease Progression")  # HIC[t] -> H[t] If intensive care was survived, start over in hospital
# rate to die from intensive care:
r = 0.05  # should be age dependent
M.addRate('HIC', 'D', r)

# cumulative total detected (= measured) cases:
M.addResult('detected', lambda State: tf.reduce_sum(State['H'], 1) + tf.reduce_sum(State['Q'], 1) + tf.reduce_sum(State['HIC'], 1) + State['CR'] + State['D'])  # ('I', 'S')
M.addResult('dead', lambda State: State['D'])  # ('I', 'S')

# M.toFit(['r0', 'hr', 'ht0', 'I0'])
# M.toFit(['r0', 'I0'])
M.toFit(['T0', 'r0', 'h', 'aT0', 'aBase', 'I0', 'q', 'd'])
# M.toFit(['r0'])

# simulated = M.simulate('simulated', {'detected': None}, Tmax=Tmax)
# M.showResults(ylabel='occupancy')
# M.showStates(MinusOne=('S'))

if False:
    otype = "L-BFGS"
    lossScale = 1.0  # 1e4
    oparam = {"normFac": 'max'}
else:
    # ToDo the local normFac is not yet recognized for the below methods
    lossScale = None
    otype = "nesterov"  # "adagrad"  "adadelta" "SGD" "nesterov"  "adam"
    learnrate = {"nesterov": 2000.0, "adam": 7e-7}
    oparam = {"learning_rate": tf.constant(learnrate[otype], dtype=stm.CalcFloatStr)}
# oparam['noiseModel'] = 'Poisson'
oparam['noiseModel'] = 'Gaussian'
# oparam['noiseModel'] = 'ScaledGaussian'  # is buggy? Why the NaNs?

measured = MeasDetected[:, :, :, 0:2] / PopSum
measuredDead = MeasDead[:, :, :, 0:2] / PopSum
NIter = 0

# tf.config.experimental_run_functions_eagerly(True)

xlim = None  # (60,100)
fittedVars, fittedRes = M.fit({'detected': measured}, Tmax, otype=otype, oparam=oparam, NIter=NIter, verbose=True, lossScale=lossScale)
M.showResults(title="District Distribution", ylabel='occupancy', xlim=xlim, dims=("District"))
M.showStates(MinusOne=('S'), dims2d=("time", "District"))

M.showResults(title="Age Distribution", ylabel='occupancy', xlim=xlim, dims=("Age"))

# np.sum(measured[-1,:,:,:],(0,2))*PopSum / Pop  # detected per population
plt.figure('hospitalization');
plt.imshow(np.squeeze(hospitalization()))

print("mean(T0) = " + str(np.mean(fittedVars['T0'])))
print("mean(r0) = " + str(np.mean(fittedVars['r0'])))
print("h = " + str(fittedVars['h']))
print("aT0 = " + str(fittedVars['aT0']))
print("aBase = " + str(fittedVars['aBase']))
print("d = " + str(fittedVars['d']))
print("q = " + str(fittedVars['q']))

plt.figure("Neuinfektionen")
plt.plot((np.sum(RawMeasDetected[1:, :, :, :], (1, 2, 3)) - np.sum(RawMeasDetected[0:-1, :, :, :], (1, 2, 3))) / np.sum(RawPopM + RawPopW) * 100000)
plt.xlabel("Tag")
plt.ylabel("Neuinfektionen / 100.000 und Tag")
offsetDay = 0  # being sunday
plt.xticks(range(offsetDay, len(Dates), 7), [date for date in Dates[offsetDay:-1:7]], rotation="vertical")
plt.xlim(45, len(Dates))
plt.tight_layout()
plt.hlines(0.25, 0, len(Dates), linestyles="dashed")
# plt.vlines(11*7, 0, 5, linestyles="dashed")

plt.figure("Awareness reduction")
plt.plot(awareness(np.arange(0,100)))

plt.figure("All Germany")
plt.semilogy(np.sum(RawMeasDetected, (1, 2, 3)),'g')
plt.semilogy(np.sum(RawMeasCured, (1, 2, 3)),'b')
plt.semilogy(np.sum(RawMeasDead, (1, 2, 3)),'m')
plt.legend(['Cases','Cured','Dead'])
offsetDay = 0  # being sunday
plt.xticks(range(offsetDay, len(Dates), 7), [date for date in Dates[offsetDay:-1:7]], rotation="vertical")
# plt.xlim(45, len(Dates))
plt.tight_layout()