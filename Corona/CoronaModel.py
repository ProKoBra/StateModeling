import StateModeling as stm
import numpy as np
import tensorflow as tf
import matplotlib.pyplot as plt
# from datetime import datetime as dt

class CoronaDelayModel(stm.Model):
    def __init__(self, AllMeasured, Tmax = 150, lossWeight={}):
        super().__init__(self, maxAxes=4, lossWeight=lossWeight)
        self.otype = "L-BFGS"; self.lossScale = 1.0; self.oparam = {"normFac": 'max'}
        self.AllMeasured = AllMeasured
        self.Tmax = Tmax
        self.PopSum = np.sum(AllMeasured['Population'])
        self.toFit(['R','infective_time','infective_sigma',
                     'death_rate','death_time','death_sigma',
                    'detect_t0','detect','detect_sigma',
                    'infect_first','infect_first_time'])  # 'infect_first','infect_first_time'
        if "Hospitalized" in AllMeasured.keys():
            self.FitVars.extend(['hospital_t0', 'hospital', 'hospital_sigma'])

        # self.toFit(['R','infect_first','infect_first_time', 'death_rate','death_time','detect_t0','detect','detect_sigma'])  #
        RInit = 1.3
        firstInf = np.nonzero(AllMeasured['Cases']>0)[0][0]
        infective_time_init = 3.0 # day in 'Disease Progression' of most probably infecting someone else
        infective_sigma_init = 1.8 # spread in 'Disease Progression' of most probably infecting someone else
        death_rate_init = 0.004 # rate of death
        death_time_init = 16.2 # day of 'Disease Progression' when death is most probable
        death_sigma_init = 2.8
        detect_t0Init = 5.0 # time when disease is typically detected
        detect_sigmaInit = 2.8
        detect_Init = 0.1 # chance that disease is finally detected (t-> inf)

        hospital_t0Init = 14.0 # time when disease is typically detected
        hospital_sigmaInit = 7.3
        hospitalization_Init = 0.1 # chance that disease is finally detected (t-> inf)

        infect_first_time_init = (1.0 + firstInf).astype(np.float32) # AllMeasured['Dates'].to_list().index('21.02.2020')+0.2   # day of first infection in the district
        infect_first_init = (AllMeasured['Cases'][firstInf] / self.PopSum/detect_Init).astype(np.float32) # Amount of first infection  (1.0 would be 5e-7 )
        infect_first_time_sigma = 1.0

        self.addAxis("Disease Progression", entries=35, queue=True)

        self.newState(name='S', axesInit=1.0)
        self.newState(name='I', axesInit={"Disease Progression": 0})
        self.newState(name='D', axesInit=0.0)
        self.newState(name='C', axesInit=0.0)
        infect_first = self.newVariables({'infect_first': infect_first_init}, forcePos=False)  # a global variable of initial infection probability
        infect_first_time = self.newVariables({"infect_first_time": infect_first_time_init}, forcePos=False, displayLog=False)  # time at which a delta is injected into the start of the progression axis
        # the initial infection is generated by "injecting" a Gaussian (to be differentiable)
        self.addRate('S', 'I', lambda t: infect_first() * self.initGaussianT0(infect_first_time(), t, sigma=infect_first_time_sigma), queueDst='Disease Progression', hasTime=True)

        AllRInit = RInit * np.ones(self.timeAxis(Tmax).shape, stm.CalcFloatStr)
        # AllRInit = RInit
        R = self.newVariables({'R': AllRInit}, forcePos=True)  #
        R_rate = lambda t: R()[t]
        RelPopulation = AllMeasured['Population'] / self.PopSum
        infective_time = self.newVariables({'infective_time': infective_time_init}, forcePos=True, displayLog=False) # day of most probably infecting someone else
        infective_sigma = self.newVariables({'infective_sigma': infective_sigma_init}, forcePos=True, displayLog=False) # day of most probably infecting someone else
        infectiveness = lambda: self.Axes['Disease Progression'].initGaussian(infective_time(), infective_sigma())
        self.addRate(('S', 'I'), 'I', lambda t: R_rate(t)*infectiveness() / RelPopulation,
                  queueDst="Disease Progression", hasTime=True)  # S ==> I[0]
        self.addRate('I', 'C', 1.0, queueSrc="Disease Progression")  # I --> C when through the queue

        death_time = self.newVariables({'death_time': death_time_init}, forcePos=False)  # most probable time of hospitalization
        death_rate = self.newVariables({'death_rate': death_rate_init})  # rate of hospitalization, should be age dependent
        death_sigma = self.newVariables({'death_sigma': death_sigma_init})  # rate of hospitalization, should be age dependent
        # influx = self.newVariables({'influx': 0.0001})  # a district dependent variable of initially infected
        # infectionRate = lambda I: (I + influx) * self.Var['r0']
        death = lambda: death_rate() * self.Axes['Disease Progression'].initGaussian(death_time(), death_sigma())
        self.addRate('I', 'D', death, resultTransfer=('deaths', 'Disease Progression'), resultScale = self.PopSum)  # I[t] -> H[t]

        detect_t0 = self.newVariables({'detect_t0': detect_t0Init}, forcePos=False)  # time when disease is typically detected
        detect_sigma = self.newVariables({'detect_sigma': detect_sigmaInit})  # time when disease (New cases!) is typically detected
        detect = self.newVariables({'detect': detect_Init})  # rate of final detection
        detection = lambda: detect() * self.Axes['Disease Progression'].initGaussian(detect_t0(), detect_sigma()) # new cases is an event. Therefore Gaussian
        self.addResult('cases', lambda State: self.PopSum * tf.reduce_sum(State['I'] * detection()))  # Only the new cases

        measured = np.squeeze(AllMeasured['Cases']) # / self.PopSum
        measuredDead = np.squeeze(AllMeasured['Dead'])  #/ self.PopSum
        self.FitDict = {'cases': measured, 'deaths': measuredDead}

        if "Hospitalized" in AllMeasured.keys():
            hospital_t0 = self.newVariables({'hospital_t0': hospital_t0Init}, forcePos=False)  # time when disease is typically detected
            hospital_sigma = self.newVariables({'hospital_sigma': hospital_sigmaInit})  # time when disease (New cases!) is typically detected
            hospital = self.newVariables({'hospital': hospitalization_Init})  # rate of final detection
            hospitalization = lambda: hospital() * self.Axes['Disease Progression'].initGaussian(hospital_t0(), hospital_sigma())  # new cases is an event. Therefore Gaussian
            self.addResult('hospitalization', lambda State: self.PopSum * tf.reduce_sum(State['I'] * hospitalization()))  # Only the new cases
            self.FitDict['hospitalization'] = np.squeeze(AllMeasured['Hospitalized']) # / self.PopSum)
        # self.FitDict = {'deaths': measuredDead}

    def doFit(self, NIter=0):
        fittedVars, fittedRes = self.fit(self.FitDict, self.Tmax, otype=self.otype, oparam=self.oparam, NIter=NIter, verbose=True, lossScale=self.lossScale)

    def showSimRes(self, ymin=0.0001,ymax=1.0):
        self.doFit()
        xlim = None  # (60,100)

        p=self.showResultsBokeh(title = self.AllMeasured['Region'], ylabel='Population',
                      xlim=xlim, subPlot='cases',
                      legendPlacement = 'upper right', figsize=[10,5], Dates=self.AllMeasured['Dates'])
        if 'Hospitalized' in self.AllMeasured:
            p=self.showResultsBokeh(title=self.AllMeasured['Region'], ylabel='Population',
                          xlim=xlim, subPlot='hospitalization',
                          legendPlacement='upper right', figsize=[10,5], Dates=self.AllMeasured['Dates'])
        p=self.showResultsBokeh(title=self.AllMeasured['Region'], ylabel='Population',
                      xlim=xlim, subPlot='deaths',
                      legendPlacement='upper right', figsize=[10,5], Dates=self.AllMeasured['Dates'])
        p=self.showResultsBokeh(title=self.AllMeasured['Region'], ylabel='Population',
                      xlim=xlim, oneMinus=['S'],
                      legendPlacement='upper right', figsize=[10,5], Dates=self.AllMeasured['Dates'], dictToPlot=self.Progression)
        p=self.showResultsBokeh(title=self.AllMeasured['Region'], ylabel='Rate',
                      xlim=xlim, subPlot='R',
                      legendPlacement='upper right', figsize=[10,5], Dates=self.AllMeasured['Dates'], dictToPlot=self.Var)
        return p


class CoronaModel(stm.Model):
    def __init__(self, AllMeasured, Tmax = 150):
        super().__init__(self, maxAxes=4)
        self.AllMeasured = AllMeasured
        self.Tmax = Tmax
        self.toFit(['r0', 'h', 'aT0', 'aBase', 'I0', 'd', 'rd', 'T0', 'q'])  # 'q',
        # self.xpos = np.arange(0, 100) / 100.0

        self.addAxis("Gender", entries=len(AllMeasured['Gender']), labels=AllMeasured['Gender'])
        self.addAxis("Age", entries=len(AllMeasured['Ages']), labels=AllMeasured['Ages'])
        self.addAxis("District", entries=len(AllMeasured['LKs']), labels=AllMeasured['LKs'])
        self.addAxis("Disease Progression", entries=28, queue=True)

        # modeling infection:
        r0Init = 9.2 * np.ones(self.Axes['Age'].shape, stm.CalcFloatStr)
        it0Init = 3.5 # day in 'Disease Progression' of most probably infecting someone else
        sigmaI = 3.0 # spread in 'Disease Progression' of most probably infecting someone else

        # model the general awareness effect:
        aT0Init = AllMeasured['Dates'].to_list().index('05.03.2020')+0.0 # Awareness effect mean day of decreasing R
        aBaseInit = 0.14 # relative drop down to this value of infectiveness cause by awareness
        aSigma = 4.0 # spread for sigmoidal awareness curve

        # modelling the german soft-lock:
        qInit = 0.0052  # lockdown quarantine percentage (has to be multiplied roughly by 3)
        sigmaQ = 1.5 # spread for soft-lock
        LockDown = AllMeasured['Dates'].to_list().index('23.03.2020')+0.0  # Time of German lockdown, Quelle: RKI bulletin
        unlock = AllMeasured['Dates'].to_list().index('20.04.2020')+0.0  # This is when retail changed! 79
        relUnlock = 0.8
        dInit = 0.13 # detection rate for quarantine from population

        # first infection
        # T0Init = AllMeasured['Dates'].index('03.03.2020')+0.2   # day of first infection in the district
        T0Init = AllMeasured['Dates'].to_list().index('21.02.2020')+0.2   # day of first infection in the district
        I0Init = 5e-9 # Amount of first infection  (1.0 would be 5e-7 )

        # hospitalization:
        hInit = 0.06 # rate of hospitalization
        AgeBorderInit = 2.3 # age limit (in bins) for probable hospitalization
        AgeSigmaInit = 0.5 # age spead (in bins) for probable hospitalization
        ht0Init = 5.5 # day of 'Disease Progression' when hospitalization is most probable
        # intensive care
        hic = 0.05  # rate to be transferred to ICUs, should really be age dependent
        rdInit = 0.05  # rate to die, should really be age dependent

        TPop = np.sum(AllMeasured['Population'])
        # susceptible
        self.newState(name='S', axesInit={"Age": 1.0, "District": AllMeasured['Population']/TPop, "Gender": 1.0})
        # I0 = self.newVariables({'I0': 0.000055 * InitPopulM}, forcePos=False)  # a district dependent variable of initially infected
        # assume 4.0 infected at time 0
        #  (2.0/323299.0) * InitPopul
        I0 = self.newVariables({'I0': I0Init}, forcePos=False)  # a global variable of initial infection probability
        # InitProgression = lambda: I0 * self.Axes['Disease Progression'].initDelta()  # variables to fit have to always be packed in lambda functions!
        # self.newState(name='I', axesInit={"Disease Progression": InitProgression, "District": None, "Age": None, "Gender": None})
        # infected (not detected):
        self.newState(name='I', axesInit={"Disease Progression": 0, "District": 0, "Age": 0, "Gender": 0})
        # cured (not detected):
        self.newState(name='C', axesInit={"District": 0, "Age": 0, "Gender": 0})
        T0 = self.newVariables({"T0": T0Init * np.ones(self.Axes['District'].shape, stm.CalcFloatStr)}, forcePos=False, displayLog=False)  # time at which a delta is injected into the start of the progression axis
        # the initial infection is generated by "injecting" a Gaussian (to be differentiable)
        self.addRate('S', 'I', lambda t: I0() * self.initGaussianT0(T0(), t), queueDst='Disease Progression', hasTime=True)

        # Age-dependent base rate of infection
        aT0 = self.newVariables({'aT0': aT0Init}, forcePos=True, displayLog=False)  # awarenessTime
        aBase = self.newVariables({'aBase': aBaseInit}, forcePos=True)  # residual relative rate after awareness effect
        awareness = lambda t: self.initSigmoidDropT0(aT0(), t, aSigma, aBase())  # 40% drop in infection rate

        it0 = self.newVariables({'it0': it0Init}, forcePos=True, displayLog=False) # day of most probably infecting someone else
        infectiveness = self.Axes['Disease Progression'].initGaussian(it0(), sigmaI)

        # InitPupulDistrictOnly = np.sum(InitPopul,(-1,-2), keepdims=True)
        r0 = self.newVariables({'r0': r0Init}, forcePos=True)
        RelPopulation = AllMeasured['Population'] / TPop
        self.addRate(('S', 'I'), 'I', lambda t: (r0()* awareness(t) * infectiveness) / RelPopulation,
                  queueDst="Disease Progression", hasTime=True, hoSumDims=['Age', 'Gender'])  # S ==> I[0]
        self.addRate('I', 'C', 1.0, queueSrc="Disease Progression")  # I --> C when through the queue

        # --- The (undetected) quarantine process:
        # susceptible, quarantined
        self.newState(name='Sq', axesInit={"District": 0, "Age": 0, "Gender": 0})
        # infected, quarantined
        self.newState(name='Iq', axesInit={"Disease Progression": 0, "District": 0, "Age": 0, "Gender": 0})
        q = self.newVariables({"q": qInit * np.ones(self.Axes['District'].shape, stm.CalcFloatStr)}, forcePos=True)  # quarantine ratio (of all ppl.) modeled as a Gaussian (see below)
        lockDownFct = lambda t: q() * self.initGaussianT0(LockDown, t, sigmaQ)
        self.addRate('S', 'Sq', lockDownFct, hasTime=True)
        unlockFct = lambda t: relUnlock * self.initDeltaT0(unlock, t, sigmaQ)
        self.addRate('I', 'Iq', lockDownFct, hasTime=True)  # S -q-> Sq
        self.addRate('Sq', 'S', unlockFct, hasTime=True)  # Sq --> S
        self.addRate('Iq', 'I', unlockFct, hasTime=True)  # Iq --> I
        self.addRate('Iq', 'C', 1.0, queueSrc="Disease Progression")  # Iq --> C when through the infection queue. Quarantine does not matter any more
        # ---------- detecting some of the infected:
        # detected quarantine state:
        self.newState(name='Q', axesInit={"Disease Progression": 0, "District": 0, "Age": 0, "Gender": 0})
        d = self.newVariables({'d': dInit}, forcePos=True)  # detection rate
        self.addRate('I', 'Q', d, resultTransfer=('cases', 'Disease Progression'))  # S -q-> Sq
        self.addRate('Iq', 'Q', d, resultTransfer=('cases', 'Disease Progression'))  # detection by testing inside the quarantine
        # ---- hospitalizing the ill
        # hospitalized state:
        self.newState(name='H', axesInit={"Disease Progression": 0, "District": 0, "Age": 0, "Gender": 0})
        ht0 = self.newVariables({'ht0': ht0Init}, forcePos=False)  # most probable time of hospitalization

        h = self.newVariables({'h': hInit})  # rate of hospitalization, should be age dependent
        # influx = self.newVariables({'influx': 0.0001})  # a district dependent variable of initially infected
        # infectionRate = lambda I: (I + influx) * self.Var['r0']
        AgeBorder = self.newVariables({'AgeBorder': AgeBorderInit}, forcePos=False, normalize=None)  # rate of hospitalization, should be age dependent
        AgeSigma = self.newVariables({'AgeSigma': AgeSigmaInit}, forcePos=False, normalize=None)  # rate of hospitalization, should be age dependent
        hospitalization = lambda: h() * self.Axes['Disease Progression'].initGaussian(ht0(), 3.0) * \
                                  self.Axes['Age'].initSigmoid(AgeBorder(), AgeSigma())
        self.addRate('I', 'H', hospitalization, resultTransfer=(('cases', 'Disease Progression'),('hospitalization', 'Disease Progression')))  # I[t] -> H[t]
        self.addRate('Q', 'H', hospitalization, resultTransfer=('hospitalization', 'Disease Progression'))  # Q[t] -> H[t]
        self.addRate('Iq', 'H', hospitalization, resultTransfer=(('cases', 'Disease Progression'),('hospitalization', 'Disease Progression')))  # Iq[t] -> H[t]

        # cured (detected):
        self.newState(name='CR', axesInit={"District": 0, "Age": 0, "Gender": 0})
        self.addRate('H', 'CR', 1.0, queueSrc="Disease Progression")  # H[t] -> CR[t]  this is a dequeueing operation and thus the rate needs to be one!
        self.addRate('Q', 'CR', 1.0, queueSrc="Disease Progression")  # H[t] -> R[t]  this is a dequeueing operation and thus the rate needs to be one!
        # ---- intensive care:
        # in intensive care
        self.newState(name='HIC', axesInit={"Disease Progression": 0, "District": 0, "Age": 0, "Gender": 0})
        # dead
        self.newState(name='D', axesInit={"District": 0, "Age": 0, "Gender": 0})
        self.addRate('H', 'HIC', hic)
        self.addRate('HIC', 'H', 1.0, queueSrc="Disease Progression")  # HIC[t] -> H[t] If intensive care was survived, start over in hospital
        # rate to die from intensive care:
        rd = self.newVariables({'rd': rdInit}, forcePos=False)  # rate to die during ICU
        self.addRate('HIC', 'D', rd, resultTransfer=('deaths', 'Disease Progression'))

        # cumulative total detected (= measured) cases:
        DPAx = - self.findAxis('Disease Progression').curAxis
        # self.addResult('cumul_cases', lambda State: tf.reduce_sum(State['H'], DPAx, keepdims=True) + tf.reduce_sum(State['Q'], DPAx, keepdims=True) +
        #                                          tf.reduce_sum(State['HIC'], DPAx, keepdims=True) + State['CR'] + State['D'])  # ('I', 'S')
        # self.addResult('cumul_dead', lambda State: State['D'])  # ('I', 'S')

        if False:
            plt.figure('hospitalization')
            toPlot = np.squeeze(hospitalization())
            if toPlot.ndim > 1:
                plt.imshow(toPlot)
            else:
                plt.plot(toPlot)

        if False:
            mobdat = AllMeasured['mobility']
            mobdate = mobdat['date'].to_numpy()
            plt.figure('Retail and recreation');
            plt.plot(mobdat['retail_and_recreation_percent_change_from_baseline'].to_numpy())
            offsetDay = 0;
            plt.xticks(range(offsetDay, len(mobdate), 7), [date for date in mobdate[offsetDay:-1:7]], rotation="vertical")
            plt.ylabel('Percent Change');
            plt.tight_layout()

        if AllMeasured['Cases'].shape[-2] > 1:
            self.toFit.append(['Age Border', 'Age Sigma'])
        self.PopSum = np.sum(AllMeasured['Population'])
        measured = AllMeasured['Cases'][:, np.newaxis, :, :, :] / self.PopSum
        measuredDead = AllMeasured['Dead'][:, np.newaxis, :, :, :] / self.PopSum

        # fittedVars, fittedRes = self.fit({'detected': measured}, self.Tmax, otype=self.otype, oparam=oparam, NIter=NIter, verbose=True, lossScale=self.lossScale)
        self.FitDict = {'cases': measured}
        if "Hospitalized" in AllMeasured.keys():
            self.FitDict['hospitalization'] = AllMeasured['Hospitalized'][:, np.newaxis, :, :, :]/ self.PopSum
        self.FitDict['deaths'] = measuredDead

        # SimDict = {'cases': None, 'cumul_cases': None, 'cumul_dead':None}

        if True:
            self.otype = "L-BFGS"
            self.lossScale = 1.0  # 1e4
            self.oparam = {"normFac": 'max'}
        else:
            self.lossScale = None
            self.otype = "nesterov"  # "adagrad"  "adadelta" "SGD" "nesterov"  "adam"
            self.learnrate = {"nesterov": 1000.0, "adam": 7e-7}
            self.oparam = {"learning_rate": tf.constant(learnrate[self.otype], dtype=stm.CalcFloatStr)}
        # oparam['noiseModel'] = 'Poisson'
        self.oparam['noiseModel'] = 'Gaussian'
        # oparam['noiseModel'] = 'ScaledGaussian'  # is buggy? Why the NaNs?
        self.doFit()

# tf.config.experimental_run_functions_eagerly(True)

    def doFit(self, NIter=0):
        fittedVars, fittedRes = self.fit(self.FitDict, self.Tmax, otype=self.otype, oparam=self.oparam, NIter=NIter, verbose=True, lossScale=self.lossScale)

    def showSimRes(self, ymin=0.0001,ymax=1.0):
        self.doFit()
        xlim = None  # (60,100)

        p=self.showResultsBokeh(title = self.AllMeasured['Region'], Scale=self.PopSum, ylabel='Population',
                      xlim=xlim, dims = ("District"), subPlot='cases',
                      legendPlacement = 'upper right',figsize=[10,5], Dates=self.AllMeasured['Dates'])
        p=self.showResultsBokeh(title = self.AllMeasured['Region'], Scale=self.PopSum, ylabel='Population',
                      xlim=xlim, dims=("District"), subPlot='hospitalization',
                      legendPlacement='upper right',figsize=[10,5], Dates=self.AllMeasured['Dates'])
        p=self.showResultsBokeh(title=self.AllMeasured['Region'], Scale=self.PopSum, ylabel='Population',
                      xlim=xlim, dims=("District"), subPlot='deaths',
                      legendPlacement='upper right',figsize=[10,5], Dates=self.AllMeasured['Dates'])
        return p


def plotTotalCases(AllMeasured):
    plt.figure("Neuinfektionen")
    # plt.plot((np.sum(RawCumulCases[1:, :, :, :], (1, 2, 3)) - np.sum(RawCumulCases[0:-1, :, :, :], (1, 2, 3))) / np.sum(RawPopM + RawPopW) * 100000)
    factor = 1.0
    if False:
        factor = 100000.0 / np.sum(AllMeasured['Population'])
        plt.ylabel("Cases / 100.000 und Tag")
    else:
        plt.ylabel("Cases")
    plt.plot(factor * np.sum(AllMeasured['Cases'][1:, :, :, :], (1, 2, 3)))
    plt.plot(factor * np.sum(10.0 * AllMeasured['Dead'][1:, :, :], (1, 2, 3)))
    if "Hospitalized" in AllMeasured.keys():
        plt.plot(factor * np.sum(AllMeasured['Hospitalized'][1:, :, :, :], (1, 2, 3)))
        plt.legend(('New Infections', 'Deaths (*10)', 'Hospitalized'))
    else:
        plt.legend(('New Infections', 'Deaths (*10)'))
    plt.xlabel("Tag")
    offsetDay = 0  # being sunday
    plt.xticks(range(offsetDay, len(AllMeasured['Dates']), 7), [date for date in AllMeasured['Dates'][offsetDay:-1:7]], rotation="vertical")
    # plt.xlim(45, len(Dates))
    plt.tight_layout()
    plt.hlines(0.25, 0, len(AllMeasured['Dead']), linestyles="dashed")
    # plt.vlines(11*7, 0, 5, linestyles="dashed")


def plotRaw(AllMeasured):
    plt.figure('Raw_'+AllMeasured['Region'])
    plt.semilogy(np.sum(AllMeasured['CumulCases'], (1, 2, 3)), 'g')
    plt.semilogy(np.sum(AllMeasured['CumulDead'], (1, 2, 3)), 'm')
    plt.semilogy(np.sum(AllMeasured['Cases'], (1, 2, 3)), 'g.-')
    plt.semilogy(np.sum(AllMeasured['Dead'], (1, 2, 3)), 'm.-')
    plt.semilogy(np.sum(AllMeasured['Cured'], (1, 2, 3)), 'b')
    if "Hospitalized" in AllMeasured.keys():
        plt.semilogy(np.sum(AllMeasured['Hospitalized'], (1, 2, 3)))
        plt.legend(['CumulCases', 'CumulDead', 'Cases', 'Deaths', 'Cured', 'Hospitalized'])
    else:
        plt.legend(['CumulCases', 'CumulDead', 'Cases', 'Deaths', 'Cured'])
    offsetDay = 0  # being sunday
    plt.xticks(range(offsetDay, len(AllMeasured['Dates']), 7), [date for date in AllMeasured['Dates'][offsetDay:-1:7]], rotation="vertical")
    # plt.xlim(45, len(Dates))
    plt.tight_layout()

