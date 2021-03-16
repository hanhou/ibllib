import unittest
import numpy as np
import pandas as pd

from copy import deepcopy
from scipy.interpolate import interp1d

try:
    from brainbox.modeling import glm
except OSError as ex:
    raise unittest.SkipTest(f"Importing pytorch failed: {ex}")


class TestModels(unittest.TestCase):

    def setUp(self):
        """
        Set up synthetic data of spikes generated by a single kernel for the GLM to fit, to test
        for the ability to recover kernels.
        """
        NTRIALS = 5000  # Number of trials of spiking to simulate
        MAXRATE = 60  # Peak rate of synthetic firing in Hz
        STIMTIME = 0.4  # Time in s where stimulus onset occurs
        KERNLEN = 0.6  # Length of kernel used to generate spikes after stimulus time
        BINSIZE = 0.005  # Size of bins in which to simulate spikes (much finer than GLM binsize)

        # Define kernel characterizing spikes in response to stimulus onset
        tstamps = np.arange(0, KERNLEN, BINSIZE)  # Stimulus kernel time stamps in 5ms increments
        tpeak = KERNLEN / 2  # Gaussian stimulus kernel peaks at 1/2 of kernel length
        spread = 1 / 8 * KERNLEN  # Spread of 1/8 kernel len ensures close-to-zero rate at end
        rawkern = np.exp(-0.5 * ((tstamps - tpeak) / spread)**2)
        stimkern = rawkern / rawkern.max() * MAXRATE

        # Pre-generate rates vectors used to generate poisson spikes
        # tstims = np.abs(np.random.normal(STIMTIME, 0.005, NTRIALS))  # Stochastic onset times
        tstims = np.ones(NTRIALS) * STIMTIME  # Fixed onset times (more stable)
        stim_idxs = np.ceil(tstims / BINSIZE).astype(int)  # Indices in binned time for onsets
        tlenmax = np.ceil((tstims.max() + KERNLEN + 0.1) / BINSIZE).astype(int)  # Max length
        stimarrs = np.zeros((NTRIALS, tlenmax))  # Array with rows of maxlen length, NTRIALs long
        stimarrs[np.arange(stimarrs.shape[0]), stim_idxs] = 1  # Set stimon indices to 1
        stimrates = []
        for i in range(NTRIALS):  # Perform convolution of kernel with each delta vector
            stimrates.append(np.convolve(stimkern, stimarrs[i])[:tlenmax] * BINSIZE)
        stimrates = np.vstack(stimrates)  # Stack into large array
        spikecounts = np.random.poisson(stimrates)  # Generate spike counts

        # Simulate trial-wise spikes from counts and store information into NeuralGLM required DF
        spksess = []
        trialinfo = []
        tlen = tlenmax * BINSIZE
        for i in range(NTRIALS):
            # Store trial info into list of dicts to be passed to pd.DataFrame
            tstart = tlen * i
            currtr = {}
            currtr['trial_start'] = tstart + 1e-3
            currtr['stimOn_times'] = tstart + tstims[i]
            currtr['trial_end'] = tstart + tlen
            trialinfo.append(currtr)

            # Simulate spikes, using pregenerated noise values
            # This is admittedly barely even pseudorandom noise but it's good enough for
            # government work
            noisevals = np.random.normal(loc=BINSIZE / 2, scale=BINSIZE / 8,
                                         size=np.sum(spikecounts[i]))
            spike_times = []
            spk_counter = 0
            for j in np.nonzero(spikecounts[i])[0]:  # For each nonzero spike count
                if j == 0:  # If the first bin has spikes, set the base spike time to a nonzero
                    curr_t = BINSIZE / 4
                else:
                    curr_t = j * BINSIZE
                for k in range(spikecounts[i, j]):  # For each spike, add the noise value and save
                    jitterspike = curr_t + noisevals[spk_counter]
                    if jitterspike < 0:  # Ensure no trial-dependent spikes occurring before tstart
                        jitterspike = 0
                    spike_times.append(jitterspike + tstart)
                    spk_counter += 1
            spksess.extend(spike_times)
        # Store into class for testing with GLM
        self.trialsdf = pd.DataFrame(trialinfo)
        self.spk_times = np.array(spksess)
        self.spk_clu = np.ones_like(self.spk_times, dtype=int)
        self.stimkern = stimkern
        self.kernt = tstamps
        self.kernlen = KERNLEN

    def test_GLM_timingkernel(self):
        # Fit a GLM to the data with a single kernel beginning at stim onset
        vartypes = {'trial_start': 'timing',
                    'stimOn_times': 'timing',
                    'trial_end': 'timing'}
        GLMBIN = 0.02  # GLM binsize in s
        nglm = glm.NeuralGLM(self.trialsdf, self.spk_times, self.spk_clu, vartypes,
                             train=1., binwidth=GLMBIN)
        bases = glm.full_rcos(self.kernlen, 10, nglm.binf)
        nglm.add_covariate_timing('stim', 'stimOn_times', bases)
        nglm.compile_design_matrix()
        skl_nglm = deepcopy(nglm)

        # Test the 'minimize' fit method first
        nglm.fit(method='minimize')
        comb_weights = nglm.combine_weights()['stim'].loc[1]
        kerninterp = interp1d(np.linspace(0, self.kernlen, self.stimkern.shape[0]),
                              self.stimkern, fill_value='extrapolate')
        subsamp = kerninterp(comb_weights.index.values)  # Need to downsample original kernel
        intercept = nglm.intercepts[1]
        # Use a weighted mean percent error in the fit vs actual kernels. Higher rates = more wt
        recovered_stimk = (1 / GLMBIN) * np.exp(comb_weights + intercept)
        error_weights = recovered_stimk / recovered_stimk.sum()
        perc_errors = np.abs((recovered_stimk / subsamp) - 1)
        wmean_err = np.sum(error_weights * perc_errors)
        self.assertTrue(wmean_err < 0.05,
                        r"Mean error in simple timing kernel recovery is over 10% in GLM with"
                        " direct objective function minimization.")

        # Test the sklearn method next
        skl_nglm.fit(method='sklearn')
        comb_weights = nglm.combine_weights()['stim'].loc[1]
        kerninterp = interp1d(np.linspace(0, self.kernlen, self.stimkern.shape[0]),
                              self.stimkern, fill_value='extrapolate')
        subsamp = kerninterp(comb_weights.index.values)  # Need to downsample original kernel
        intercept = nglm.intercepts[1]
        # Use a weighted mean percent error in the fit vs actual kernels. Higher rates = more wt
        recovered_stimk = (1 / GLMBIN) * np.exp(comb_weights + intercept)
        error_weights = recovered_stimk / recovered_stimk.sum()
        perc_errors = np.abs((recovered_stimk / subsamp) - 1)
        wmean_err = np.sum(error_weights * perc_errors)
        self.assertTrue(wmean_err < 0.05,
                        r"Mean error in simple timing kernel recovery is over 5% in GLM with"
                        " sklearn deviance-based optimization.")


if __name__ == '__main__':
    unittest.main()
