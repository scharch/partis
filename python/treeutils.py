import __builtin__
import glob
import operator
import string
import itertools
import copy
import collections
import random
import csv
from cStringIO import StringIO
import subprocess
import tempfile
import os
import numpy
import sys
from distutils.version import StrictVersion
import dendropy
import time
import math
import json
import pickle
import warnings
import traceback
if StrictVersion(dendropy.__version__) < StrictVersion('4.0.0'):  # not sure on the exact version I need, but 3.12.0 is missing lots of vital tree fcns
    raise RuntimeError("dendropy version 4.0.0 or later is required (found version %s)." % dendropy.__version__)
import yaml
try:
    from yaml import CLoader as Loader, CDumper as Dumper
except ImportError:
    from yaml import Loader, Dumper

import utils

# ----------------------------------------------------------------------------------------
fmetrics = ['lbf', 'aa-lbf']
affy_metrics = ['lbi', 'cons-dist-aa', 'cons-dist-nuc', 'shm', 'shm-aa', 'aa-lbi', 'cons-lbi']  # it would be nice to instead use the info at the top of treeutils/lbplotting
# affy_metrics += ['sum-'+m for m in affy_metrics]
daffy_metrics = ['delta-lbi', 'lbr', 'aa-lbr'] + fmetrics
# daffy_metrics += ['sum-'+m for m in daffy_metrics]

lb_metrics = collections.OrderedDict(('lb' + let, 'lb ' + lab) for let, lab in (('i', 'index'), ('r', 'ratio'), ('f', 'fraction')))
selection_metrics = ['lbi', 'lbr', 'lbf', 'cons-dist-aa', 'cons-frac-aa', 'aa-lbi', 'aa-lbr', 'aa-lbf', 'shm', 'shm-aa']
typical_bcr_seq_len = 400
# default_lb_tau = 0.0025
# default_lbr_tau_factor = 1
default_min_selection_metric_cluster_size = 10

dummy_str = 'x-dummy-x'

legtexts = {
    'metric-for-target-distance' : 'target dist. metric',
    'n-sim-seqs-per-generation' : 'N sampled',
    'leaf-sampling-scheme' : 'sampling scheme',
    'target-count' : 'N target seqs',
    'n-target-clusters' : 'N target clust.',
    'min-target-distance' : 'min target dist.',
    'uniform-random' : 'unif. random',
    'affinity-biased' : 'affinity biased',
    'high-affinity' : 'perf. affinity',
    'cons-dist-aa' : 'aa-cdist',
    # 'sum-cons-dist-aa' : '- AA dist. to cons seq (h+l)',
    'cons-frac-aa' : 'aa-cfrac',
    'cons-dist-nuc' : 'nuc-cdist',
    'shm' : 'n-shm',
    'shm-aa' : 'n-shm-aa',
    'aa-lbi' : 'AA lb index',
    'aa-lbr' : 'AA lb ratio',
    'aa-lbf' : 'AA lb fraction',
    # 'sum-aa-lbi' : 'h+l AA lb index',
    # 'sum-aa-lbr' : 'h+l AA lb ratio',
    # 'sum-lbi' : 'h+l lb index',
    # 'sum-lbr' : 'h+l lb ratio',
    # 'sum-n_mutations' : 'h+l nuc mutations',
    # 'sum-shm' : 'h+l nuc mutations',
    # 'sum-shm-aa' : 'h+l AA mutations',
}

# ----------------------------------------------------------------------------------------
all_plot_cfg = ['lb-vs-affy', 'slice', 'joy', 'lb-vs-daffy', 'lb-scatter', 'tree', 'distr', 'true-vs-inf-metrics', 'tree-mut-stats']
default_plot_cfg = ['lb-vs-affy', 'slice', 'joy', 'lb-vs-daffy', 'lb-scatter', 'tree']

# ----------------------------------------------------------------------------------------
def smetric_fname(fname):
    if utils.getsuffix(fname) == '':  # directory (paired loci)
        return '%s/selection-metrics.yaml' % fname
    else:
        return utils.insert_before_suffix('-selection-metrics', fname)

# ----------------------------------------------------------------------------------------
def add_cons_seqs(line, aa=False):
    ckey = 'consensus_seq'
    if ckey not in line:
        line[ckey] = utils.cons_seq_of_line(line)
    if aa:
        ckey += '_aa'
        if ckey not in line:
            line[ckey] = utils.cons_seq_of_line(line, aa=True)

# ----------------------------------------------------------------------------------------
def lb_cons_dist(line, iseq, aa=False, frac=False):  # at every point where this can add something to <line> (i.e. consensus seqs and aa seqs) it checks that they're not already there, so it will never do those calculations twice. But the final hamming calculation is *not* cached so will get redone if you call more than once
    if aa and 'seqs_aa' not in line:
        utils.add_seqs_aa(line)
    add_cons_seqs(line, aa=aa)
    tstr = '_aa' if aa else ''
    hfcn = utils.hamming_fraction if frac else utils.hamming_distance  # NOTE it's important to use this if you want the fraction (rather than dividing by sequence length afterward) since you also need to account for ambig bases in the cons seq
    return hfcn(line['consensus_seq'+tstr], line['seqs'+tstr][iseq], amino_acid=aa)

# ----------------------------------------------------------------------------------------
def add_cons_dists(line, aa=False, debug=False):
    ckey = 'cons_dists_' + ('aa' if aa else 'nuc')
    if ckey not in line:
        line[ckey] = [lb_cons_dist(line, i, aa=aa) for i, u in enumerate(line['unique_ids'])]
    if debug:  # it would kind of make more sense to have this in some of the fcns that this fcn is calling, but then I'd have to pass the debug arg through a bunch of tiny fcns that don't really need it 
        tstr = '_aa' if aa else ''
        # don't need this unless we turn the tie resolver stuff back on:
        # if aa:  # we have to add this by hand since we don't actually use it to calculate the aa cons seq -- we get that by just translating the nuc cons seq
        #     utils.add_naive_seq_aa(line)
        hfkey = ckey.replace('cons_dists_', 'cons_fracs_')
        line[hfkey] = [lb_cons_dist(line, i, aa=aa, frac=True) for i, u in enumerate(line['unique_ids'])]
        extra_keys = [ckey, hfkey]
        if 'cell-types' in line:
            extra_keys.append('cell-types')
        utils.print_cons_seq_dbg(utils.seqfos_from_line(line, aa=aa, extra_keys=extra_keys), line['consensus_seq'+tstr], align=False, aa=aa)  # NOTE you probably don't want to turn the naive tie resolver back on in utils.cons_seq_of_line(), but if you do, this reminds you to also do it here so the dbg is correct, tie_resolver_seq=line['naive_seq'+tstr], tie_resolver_label='naive seq')

# ----------------------------------------------------------------------------------------
def add_cdists_to_lbfo(line, lbfo, cdist, debug=False):  # it's kind of dumb to store them both in <line> and in <lbfo> (and thus in <line['tree-info']['lb']>), but I think it's ultimately the most sensible thing, given the inherent contradiction that a) we want to *treat* the cons dists like lbi/lbr tree metrics in almost every way, but b) they're *not* actually tree metrics in the sense that they don't use a tree (also, we want the minus sign in lbfo)
    add_cons_dists(line, aa='-aa' in cdist, debug=debug)
    tkey = cdist.replace('cons-dist-', 'cons_dists_')  # yes, I want the names to be different (although admittedly with a time machine it'd be set up differently)
    lbfo[cdist] = {u : -line[tkey][i] for i, u in enumerate(line['unique_ids'])}

# ----------------------------------------------------------------------------------------
# if neither iseq nor uid are set, returns all of the values; otherwise specify *either* iseq or uid
def smvals(line, smetric, iseq=None, uid=None, nullval=None):  # retrieve selection metric values from within line['tree-info']['lb'][yadda yadda], i.e. as if they were a normal list-based per-seq quantity
    # NOTE this is what you use if the values are already there, in 'tree-info' -- if you want to calculate them, there's other fcns
    assert (iseq is None and uid is None) or [iseq, uid].count(None) == 1
    if uid is not None:
        iseq = line['unique_ids'].index(uid)
    if smetric in line:
        raise Exception('called smvals() with normal list-based key %s' % smetric)
    if 'tree-info' not in line or 'lb' not in line['tree-info'] or smetric not in line['tree-info']['lb']:
        return [nullval for _ in line['unique_ids']] if iseq is None else nullval
    lbfo = line['tree-info']['lb'][smetric]
    if iseq is None:
        return [lbfo.get(u, nullval) for u in line['unique_ids']]
    else:
        return lbfo.get(line['unique_ids'][iseq], nullval)

# ----------------------------------------------------------------------------------------
def lb_cons_seq_shm(line, aa=False):
    add_cons_seqs(line, aa=aa)
    if aa and 'naive_seq_aa' not in line:
        utils.add_naive_seq_aa(line)
    tstr = '_aa' if aa else ''
    return utils.hamming_distance(line['naive_seq'+tstr], line['consensus_seq'+tstr], amino_acid=aa)

# ----------------------------------------------------------------------------------------
def edge_dist_fcn(dtree, uid):  # duplicates fcn in lbplotting.make_lb_scatter_plots()
    node = dtree.find_node_with_taxon_label(uid)
    if node is None:
        return None
    return min(node.distance_from_tip(), node.distance_from_root())  # NOTE the tip one gives the *maximum* distance to a leaf, but I think that's ok

# ----------------------------------------------------------------------------------------
cgroups = ['within-families', 'among-families']  # different ways of grouping clusters, i.e. "cluster groupings"
dtr_targets = {'within-families' : ['affinity', 'delta-affinity'], 'among-families' : ['affinity', 'delta-affinity']}  # variables that we try to predict, i.e. we train on dtr for each of these
pchoices = ['per-seq', 'per-cluster']  # per-? choice, i.e. is this a per-sequence or per-cluster quantity
dtr_metrics = ['%s-%s-dtr'%(cg, tv) for cg in cgroups for tv in dtr_targets[cg]]  # NOTE order of this has to remain the same as in the loops used to generate it
dtr_vars = {'within-families' : {'per-seq' : ['lbi', 'cons-dist-nuc', 'cons-dist-aa', 'edge-dist', 'lbr', 'lbf', 'shm', 'shm-aa'],  # NOTE when iterating over this, you have to take the order from <pchoices>, since both pchoices go into the same list of variable values
                                 'per-cluster' : []},
            'among-families' : {'per-seq' : ['lbi', 'cons-dist-nuc', 'cons-dist-aa', 'edge-dist', 'lbr', 'lbf', 'shm', 'shm-aa'],
                                'per-cluster' : ['fay-wu-h', 'cons-seq-shm-nuc', 'cons-seq-shm-aa', 'mean-shm', 'max-lbi', 'max-lbr']},
            }
default_dtr_options = {
    # 'base-regr' :
    'vars' : None,  # uses <dtr_vars> for default
    'min_samples_leaf' : 5,  # only used for grad-boost and bag
    'max_depth' : 5,  # only used for grad-boost and bag
    'ensemble' : 'grad-boost',  # ['bag', 'forest', 'ada-boost',
    'n_estimators' : 100,
    'n_train_per_family' : 1,  # for among-families dtr, only train on this many cells per family (to avoid over training). Set to None to use all of 'em
    'n_jobs' : None,  # default set below (also, this is not used for boosted ensembles)
}

# ----------------------------------------------------------------------------------------
def get_dtr_varnames(cgroup, varlists, with_pc=False):  # arg, <with_pc> is fucking ugly
    return [(pc, vn) if with_pc else vn for pc in pchoices for vn in varlists[cgroup][pc]]

# ----------------------------------------------------------------------------------------
def get_dtr_vals(cgroup, varlists, line, lbfo, dtree):
    # ----------------------------------------------------------------------------------------
    def getval(pchoice, var, uid):
        if pchoice == 'per-seq':
            if var in ['lbi', 'lbr', 'lbf', 'cons-dist-nuc', 'cons-dist-aa']:
                return lbfo[var][uid]  # NOTE this will fail in (some) cases where the uids in the tree and annotation aren't the same, but I don't care atm since it looks like we won't really be using the dtr
            elif var == 'edge-dist':
                return edge_dist_fcn(dtree, uid)
            elif var == 'shm':
                return utils.per_seq_val(line, 'n_mutations', uid)
            elif var == 'shm-aa':
                return utils.shm_aa(line, line['unique_ids'].index(uid))
            else:
                assert False
        elif pchoice == 'per-cluster':
            return per_cluster_vals[var]
        else:
            assert False
    # ----------------------------------------------------------------------------------------
    if cgroup == 'among-families':
        per_cluster_vals = {
            'cons-seq-shm-nuc' : lb_cons_seq_shm(line),
            'cons-seq-shm-aa' : lb_cons_seq_shm(line, aa=True),
            'fay-wu-h' : -utils.fay_wu_h(line),
            'mean-shm' : numpy.mean(line['n_mutations']),
            'max-lbi' : max(lbfo['lbi'].values()),
            'max-lbr' : max(lbfo['lbr'].values()),
        }
    vals = []
    for uid in line['unique_ids']:
        vals.append([getval(pc, var, uid) for pc, var in get_dtr_varnames(cgroup, varlists, with_pc=True)])
    return vals

# ----------------------------------------------------------------------------------------
def dtrfname(dpath, cg, tvar, suffix='pickle'):
    return '%s/%s-%s-dtr-model.%s' % (dpath, cg, tvar, suffix)

# ----------------------------------------------------------------------------------------
def tmfname(plotdir, metric, x_axis_label, cg=None, tv=None, use_relative_affy=False):  # tree metric fname
    assert x_axis_label in ['affinity', 'n-ancestor']  # arg, this is messy
    assert tv in [None, 'affinity', 'delta-affinity']
    metric_str = metric if metric != 'dtr' else '-'.join([cg, tv, metric])
    vs_str = '%s-vs%s-%s' % (metric_str, '-relative' if x_axis_label == 'affinity' and use_relative_affy else '', x_axis_label)
    return '%s/true-tree-metrics/%s/%s-ptiles/%s-true-tree-ptiles-all-clusters.yaml' % (plotdir, metric_str, vs_str, vs_str)  # NOTE has 'true-tree' in there, which is fine for now but may need to change

# ----------------------------------------------------------------------------------------
def write_pmml(pmmlfname, dmodel, varlist, targetvar):
    try:  # seems to crash for no @**($ing reason sometimes
        if 'sklearn2pmml' not in sys.modules:  # just so people don't need to install/import it if they're not training
            import sklearn2pmml
        pmml_pipeline = sys.modules['sklearn2pmml'].make_pmml_pipeline(dmodel, active_fields=varlist, target_fields=targetvar)
        sys.modules['sklearn2pmml'].sklearn2pmml(pmml_pipeline, pmmlfname)
    except:
        elines = traceback.format_exception(*sys.exc_info())
        print utils.pad_lines(''.join(elines))
        print '  %s pmml conversion failed (see above), but continuing' % utils.color('red', 'error')

# ----------------------------------------------------------------------------------------
def train_dtr_model(trainfo, outdir, cfgvals, cgroup, tvar):
    if os.path.exists(dtrfname(outdir, cgroup, tvar)):
        print '  %s dtr model file exists, so skipping training: %s' % (utils.color('yellow', 'warning'), dtrfname(outdir, cgroup, tvar))
        return
    if 'sklearn.ensemble' not in sys.modules:
        with warnings.catch_warnings():  # NOTE not sure this is actually catching the warnings UPDATE oh, I think the warnings are getting thrown by function calls, not imports
            warnings.simplefilter('ignore', category=DeprecationWarning)  # numpy is complaining about how sklearn is importing something, and I really don't want to *@*($$ing hear about it
            from sklearn import tree
            from sklearn import ensemble
    skens = sys.modules['sklearn.ensemble']
    sktree = sys.modules['sklearn.tree']

    start = time.time()
    base_kwargs, kwargs = {}, {'n_estimators' : cfgvals['n_estimators']}
    if cfgvals['ensemble'] == 'bag':
        base_kwargs = {'min_samples_leaf' : cfgvals['min_samples_leaf'], 'max_depth' : cfgvals['max_depth']}
        kwargs['base_estimator'] = sktree.DecisionTreeRegressor(**base_kwargs)  # we can pass this to ada-boost, but I'm not sure if we should (it would override the default max_depth=3, for instance)
    if 'grad-boost' in cfgvals['ensemble']:
        kwargs['max_depth'] = cfgvals['max_depth']
        kwargs['min_samples_leaf'] = cfgvals['min_samples_leaf']
    if 'boost' not in cfgvals['ensemble']:
        kwargs['n_jobs'] = cfgvals['n_jobs']

    if cfgvals['ensemble'] == 'bag':
        model = skens.BaggingRegressor(**kwargs)
    elif cfgvals['ensemble'] == 'forest':
        model = skens.RandomForestRegressor(**kwargs)
    elif cfgvals['ensemble'] == 'ada-boost':
        model = skens.AdaBoostRegressor(**kwargs)
    elif cfgvals['ensemble'] == 'grad-boost':
        model = skens.GradientBoostingRegressor(**kwargs)  # if too slow, maybe try the new hist gradient boosting stuff
    else:
        assert False

    model.fit(trainfo['in'], trainfo['out'])  #, sample_weight=trainfo['weights'])

    tmpkeys = [k for k in cfgvals if k != 'vars' and (k in kwargs or k in base_kwargs)]  # don't want to print the inapplicable ones
    print '    %s-families %s (%d observations in %.1fs):  %s' % (utils.color('green', cgroup.split('-')[0]), utils.color('blue', tvar), len(trainfo['in']), time.time() - start, '   '.join('%s %s'%(k, cfgvals[k]) for k in sorted(tmpkeys)))
    print '         feature importances:'
    print '                                   mean   err'
    for iv, vname in enumerate([v for pc in pchoices for v in cfgvals['vars'][cgroup][pc]]):
        if cfgvals['ensemble'] == 'grad-boost':
            filist = [model.feature_importances_[iv]]
        else:
            filist = [estm.feature_importances_[iv] for estm in model.estimators_]
        wlist = None
        if cfgvals['ensemble'] == 'ada-boost':
            wlist = [w for w in model.estimator_weights_ if w > 0]
            assert len(wlist) == len(model.estimators_)  # it terminates early (i.e. before making all the allowed estimators) if it already has perfect performance, but doesn't leave the lists the same length
        print '               %17s   %5.3f  %5.3f' % (vname, numpy.average(filist, weights=wlist), (numpy.std(filist, ddof=1) / math.sqrt(len(filist))) if len(filist) > 1 else 0.)  # NOTE not sure if std should also use the weights

    if not os.path.exists(outdir):
        os.makedirs(outdir)
    if 'joblib' not in sys.modules:  # just so people don't need to install it unless they're training (also scons seems to break it https://stackoverflow.com/questions/24453387/scons-attributeerror-builtin-function-or-method-object-has-no-attribute-disp)
        import joblib
    with open(dtrfname(outdir, cgroup, tvar), 'w') as dfile:
        sys.modules['joblib'].dump(model, dfile)
    write_pmml(dtrfname(outdir, cgroup, tvar, suffix='pmml'), model, get_dtr_varnames(cgroup, cfgvals['vars']), tvar)

# ----------------------------------------------------------------------------------------
def get_lb_bounds(tau, seq_len):
    if tau != 1. / seq_len:
        raise Exception('tau now has to equal 1 / len(seq) in order to normalize lb metrics')
    bvals = [
        (300, 0.0219),
        (400, 0.0169),
        (500, 0.0135),
        (600, 0.0119),
        (700, 0.0091),
        (900, 0.0073),
    ]
    slvals = [l for l, _ in bvals]
    if seq_len < min(slvals) or seq_len > max(slvals):
        print '  %s seq len %d outside known interpolation values [%d, %d], probably need to rerun test/cf-tree-metrics.py --actions get-lb-bounds to cover this seq len' % (utils.wrnstr(), seq_len, min(slvals), max(slvals))
    (len1, max1), (len2, max2) = sorted(bvals, key=lambda x: abs(x[0] - seq_len))[:2]
    return tau, utils.intexterpolate(len1, max1, len2, max2, seq_len)

# old way:
# # ----------------------------------------------------------------------------------------
# # NOTE the min lbi is just tau, but I still like doing it this way
# lb_bounds = {  # calculated to 17 generations, which is quite close to the asymptote
#     400 : {  # seq_len
#         0.0030: (0.0030, 0.0331),  # if tau is any bigger than this it doesn't really converge
#         0.0025: (0.0025, 0.0176),
#         0.0020: (0.0020, 0.0100),
#         0.0010: (0.0010, 0.0033),
#         0.0005: (0.0005, 0.0015),
#     },
#     # it turns out the aa lb metrics need the above nuc normalization (i.e. if we normalize with the below, the values are huge, like lots are 10ish). I guess maybe this makes sense, since i'm taking the nuc tree topology and scaling it to aa
#     # int(typical_bcr_seq_len / 3.) : {  # amino acid (133)
#     #     0.0030: (0.0030, 0.0099),
#     #     0.0025: (0.0025, 0.0079),
#     #     0.0020: (0.0020, 0.0061),
#     #     0.0010: (0.0010, 0.0030),
#     #     0.0005: (0.0005, 0.0015),
#     # }
# }

# ----------------------------------------------------------------------------------------
def normalize_lb_val(metric, lbval, tau, seq_len):
    assert metric == 'lbi'
    lbmin, lbmax = get_lb_bounds(tau, seq_len)
    return (lbval - lbmin) / (lbmax - lbmin)

# ----------------------------------------------------------------------------------------
def get_treestrs_from_file(treefname, n_expected_trees=None):
    with open(treefname) as treefile:
        tlines = treefile.readlines()
    if n_expected_trees is not None and len(tlines) != n_expected_trees:
        raise Exception('expected %d tree%s, but read %d tree lines from %s' % (n_expected_trees, utils.plural(n_expected_trees), len(tlines), treefname))
    return tlines

# ----------------------------------------------------------------------------------------
def get_treestr_from_file(treefname):
    return get_treestrs_from_file(treefname, n_expected_trees=1)[0]

# ----------------------------------------------------------------------------------------
def as_str(dtree):  # just a shortand (adding this very late, so could stand to add this to a lot of paces that use dtree.as_string())
    return dtree.as_string(schema='newick').strip()

# ----------------------------------------------------------------------------------------
def cycle_through_ascii_conversion(dtree=None, treestr=None, taxon_namespace=None):  # run once through the cycle of str -> dtree -> str (or dtree -> str -> dtree)
    if dtree is not None:
        return get_dendro_tree(treestr=as_str(dtree), taxon_namespace=taxon_namespace)
    elif treestr is not None:
        return as_str(get_dendro_tree(treestr=treestr))
    else:
        assert False

# ----------------------------------------------------------------------------------------
def get_dendro_tree(treestr=None, treefname=None, taxon_namespace=None, schema='newick', ignore_existing_internal_node_labels=False, suppress_internal_node_taxa=False, no_warn=False, debug=False):  # specify either <treestr> or <treefname>
    # <ignore_existing_internal_node_labels> is for when you want the internal nodes labeled (which we usually do, since we want to calculate selection metrics for internal nodes), but you also want to ignore the existing internal node labels (e.g. with FastTree output, where they're floats)
    # <suppress_internal_node_taxa> on the other hand is for when you don't want to have taxa for any internal nodes (e.g. when calculating the tree difference metrics, the two trees have to have the same taxon namespace, but since they in general have different internal nodes, the internal nodes can't have taxa)
    assert treestr is None or treefname is None
    if ignore_existing_internal_node_labels and suppress_internal_node_taxa:
        raise Exception('doesn\'t make sense to specify both')
    if treestr is None:
        treestr = get_treestr_from_file(treefname)
    if debug:
        print '   getting dendro tree from string:\n     %s' % treestr
        if taxon_namespace is not None:
            print '     and taxon namespace:  %s' % ' '.join([t.label for t in taxon_namespace])
    # dendropy doesn't make taxons for internal nodes by default, so it puts the label for internal nodes in node.label instead of node.taxon.label, but it crashes if it gets duplicate labels, so you can't just always turn off internal node taxon suppression
    dtree = dendropy.Tree.get_from_string(treestr, schema, taxon_namespace=taxon_namespace, suppress_internal_node_taxa=(ignore_existing_internal_node_labels or suppress_internal_node_taxa), preserve_underscores=True, rooting='force-rooted')  # make sure the tree is rooted, to avoid nodes disappearing in remove_dummy_branches() (and proably other places as well)
    if dtree.seed_node.edge_length > 0 and not no_warn:
        # this would be easy to fix, but i think it only happens from simulation trees from treegenerator UPDATE ok also happens for trees from the linearham paper
        print '  %s seed/root node has non-zero edge length (i.e. there\'s a branch above it)' % utils.color('red', 'warning')
    label_nodes(dtree, ignore_existing_internal_node_labels=ignore_existing_internal_node_labels, suppress_internal_node_taxa=suppress_internal_node_taxa, debug=debug)  # set internal node labels to any found in <treestr> (unless <ignore_existing_internal_node_labels> is set), otherwise make some up (e.g. aa, ab, ac)

    # # uncomment for more verbosity: NOTE node label check will likely fail if suppress_internal_node_taxa is set
    # check_node_labels(dtree, debug=debug)  # makes sure that for all nodes, node.taxon is not None, and node.label *is* None (i.e. that label_nodes did what it was supposed to, as long as suppress_internal_node_taxa wasn't set)
    # if debug:
    #     print utils.pad_lines(get_ascii_tree(dendro_tree=dtree))

    return dtree

# ----------------------------------------------------------------------------------------
def import_bio_phylo():
    if 'Bio.Phylo' not in sys.modules:
        from Bio import Phylo  # slow af to import
    return sys.modules['Bio.Phylo']

# ----------------------------------------------------------------------------------------
def get_bio_tree(treestr=None, treefname=None, schema='newick'):  # NOTE don't use this in future (all current uses are commented)
    Phylo = import_bio_phylo()
    if treestr is not None:
        return Phylo.read(StringIO(treestr), schema)
    elif treefname is not None:
        with open(treefname) as treefile:
            return Phylo.read(treefile, schema)
    else:
        assert False

# ----------------------------------------------------------------------------------------
def get_imbalance(dtree, treetype='dendropy'):  # tree imbalance as std dev in root-to-tip branch lengths (see here https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1008030#pcbi-1008030-g001)
    depths = get_leaf_depths(dtree, treetype=treetype)
    imbal = numpy.std(depths.values(), ddof=1)
    # print utils.pad_lines(get_ascii_tree(dendro_tree=dtree))
    # print ' '.join(['%.3f'%v for v in sorted(depths.values())])
    # print 'imbal', imbal
    return imbal

# ----------------------------------------------------------------------------------------
def get_leaf_depths(tree, treetype='dendropy'):  # NOTE structure of dictionary may depend on <treetype>, e.g. whether non-named nodes are included (maybe it doesn't any more? unless you return <clade_keyed_depths> at least)
    if treetype == 'dendropy':
        depths = {n.taxon.label : n.distance_from_root() for n in tree.leaf_node_iter()}
    elif treetype == 'Bio':
        clade_keyed_depths = tree.depths()  # keyed by clade, not clade name (so unlabelled nodes are accessible)
        depths = {n.name : clade_keyed_depths[n] for n in tree.find_clades()}
    else:
        assert False

    return depths

# ----------------------------------------------------------------------------------------
def get_n_leaves(tree):
    return len(tree.leaf_nodes())

# ----------------------------------------------------------------------------------------
def get_n_nodes(tree):
    return len(list(tree.preorder_node_iter()))

# ----------------------------------------------------------------------------------------
def collapse_nodes(dtree, keep_name, remove_name, keep_name_node=None, remove_name_node=None, debug=False):  # collapse edge between <keep_name> and <remove_name>, leaving remaining node with name <keep_name>
    # NOTE I wrote this to try to fix the phylip trees from lonr.r, but it ends up they're kind of unfixable... but this fcn may be useful in the future, I guess, and it works UPDATE yep using it now for something else
    if debug:
        print '    collapsing %s and %s (the former will be the label for the surviving node)' % (keep_name, remove_name)
        print utils.pad_lines(get_ascii_tree(dendro_tree=dtree))
    if keep_name_node is None:
        keep_name_node = dtree.find_node_with_taxon_label(keep_name)
    if remove_name_node is None:
        assert remove_name is not None  # if we *are* passed <remove_name_node>, it's ok for <remove_name> to be None
        remove_name_node = dtree.find_node_with_taxon_label(remove_name)
    swapped = False
    if keep_name_node in remove_name_node.child_nodes():
        assert remove_name_node not in keep_name_node.child_nodes()
        parent_node = remove_name_node
        if parent_node.taxon is None:
            parent_node.taxon = dendropy.Taxon()
        parent_node.taxon.label = keep_name  # have to rename it, since we always actually keep the parent
        swapped = True
        child_node = keep_name_node
    elif remove_name_node in keep_name_node.child_nodes():
        assert keep_name_node not in remove_name_node.child_nodes()
        parent_node = keep_name_node
        child_node = remove_name_node
    else:
        print '    node names %s and %s don\'t share an edge:' % (keep_name, remove_name)
        print '        keep node children: %s' % ' '.join([n.taxon.label for n in keep_name_node.child_nodes()])
        print '      remove node children: %s' % ' '.join([n.taxon.label for n in remove_name_node.child_nodes()])
        raise Exception('see above')

    if child_node.is_leaf():
        dtree.prune_taxa([child_node.taxon], suppress_unifurcations=False)
        if debug:
            print '       pruned leaf node %s' % (('%s (renamed parent to %s)' % (remove_name, keep_name)) if swapped else remove_name)
    else:
        found = False
        for edge in parent_node.child_edge_iter():
            if edge.head_node is child_node:
                edge.collapse()  # removes child node (in dendropy language: inserts all children of the head_node (child) of this edge as children of the edge's tail_node (parent)) Doesn't modify edge lengths by default (i.e. collapsed edge should have zero length).
                found = True
                break
        assert found
        if debug:
            print '     collapsed edge between %s and %s' % (keep_name, remove_name)

    if debug:
        print utils.pad_lines(get_ascii_tree(dendro_tree=dtree))
    assert dtree.find_node_with_taxon_label(remove_name) is None

    # NOTE do i need to add this?
    # dtree.purge_taxon_namespace()

# ----------------------------------------------------------------------------------------
def check_node_labels(dtree, debug=False):
    if debug:
        print 'checking node labels for:'
        print utils.pad_lines(get_ascii_tree(dendro_tree=dtree, width=250))
    for node in dtree.preorder_node_iter():
        if node.taxon is None:
            raise Exception('taxon is None for node with depth %f' % node.distance_from_root())
        if debug:
            print '    ok: %s' % node.taxon.label
        if node.label is not None:
            raise Exception('node.label not set to None')

# ----------------------------------------------------------------------------------------
# by default, mostly adds labels to internal nodes (also sometimes the root node) that are missing them
def label_nodes(dendro_tree, ignore_existing_internal_node_labels=False, ignore_existing_internal_taxon_labels=False, suppress_internal_node_taxa=False, initial_length=3, debug=False):
    if ignore_existing_internal_node_labels and suppress_internal_node_taxa:
        raise Exception('doesn\'t make sense to specify both')
    if debug:
        print '   labeling nodes'
        # print '    before:'
        # print utils.pad_lines(get_ascii_tree(dendro_tree))
    tns = dendro_tree.taxon_namespace
    initial_names = set([t.label for t in tns])  # should all be leaf nodes, except the naive sequence (at least for now)
    if debug:
        print '           initial taxon labels: %s' % ' '.join(sorted(initial_names))
        no_taxon_nodes = [n for n in dendro_tree.preorder_node_iter() if n.taxon is None]
        if len(no_taxon_nodes) > 0:
            print '               %d node%s with no taxa and depths: %s' % (len(no_taxon_nodes), utils.plural(len(no_taxon_nodes)), ' '.join('%.4f'%n.distance_from_root() for n in no_taxon_nodes))
    potential_names, used_names = None, None
    new_label, potential_names, used_names = utils.choose_new_uid(potential_names, used_names, initial_length=initial_length, shuffle=True)
    skipped_dbg, relabeled_dbg = [], []
    for node in dendro_tree.preorder_node_iter():
        if node.taxon is not None and not (ignore_existing_internal_taxon_labels and not node.is_leaf()):
            skipped_dbg += ['%s' % node.taxon.label]
            assert node.label is None  # if you want to change this, you have to start setting the node labels in build_lonr_tree(). For now, I like having the label in _one_ freaking place
            continue  # already properly labeled

        current_label = node.label
        node.label = None
        if suppress_internal_node_taxa and not node.is_leaf():
            continue

        if current_label is None or ignore_existing_internal_node_labels:
            new_label, potential_names, used_names = utils.choose_new_uid(potential_names, used_names)
        else:
            # turning this off since it's slow, and has been here a while without getting tripped (and I'm pretty sure the tns checks, anyway)
            # if tns.has_taxon_label(current_label):
            #     raise Exception('duplicate node label \'%s\'' % current_label)
            new_label = current_label

        # turning this off since it's slow, and has been here a while without getting tripped (and I'm pretty sure the tns checks, anyway)
        # if tns.has_taxon_label(new_label):
        #     raise Exception('failed labeling internal nodes (chose name \'%s\' that was already in the taxon namespace)' % new_label)

        node.taxon = dendropy.Taxon(new_label)
        tns.add_taxon(node.taxon)
        relabeled_dbg += ['%s' % new_label]

    if debug:
        print '      skipped (already labeled): %s' % ' '.join(sorted(skipped_dbg))
        print '                   (re-)labeled: %s' % ' '.join(sorted(relabeled_dbg))
        # print '   after:'
        # print utils.pad_lines(get_ascii_tree(dendro_tree))

# ----------------------------------------------------------------------------------------
def translate_labels(dendro_tree, translation_pairs, dbgstr='', dont_fail=False, debug=False):
    if debug:
        print '    translating %stree:' % ('' if dbgstr=='' else dbgstr+' ')
        print get_ascii_tree(dendro_tree=dendro_tree, extra_str='      ')
    for old_label, new_label in translation_pairs:
        taxon = dendro_tree.taxon_namespace.get_taxon(old_label)
        if taxon is None:
            prstr = 'requested taxon with old name \'%s\' not present in tree (present: %s)' % (old_label, ' '.join(t.label for t in dendro_tree.taxon_namespace))
            if dont_fail:
                print prstr
                continue
            else:
                raise Exception(prstr)
        taxon.label = new_label
        if debug:
            print '    %20s --> %s' % (old_label, new_label)
    if debug:
        print get_ascii_tree(dendro_tree=dendro_tree, extra_str='      ')

# ----------------------------------------------------------------------------------------
def write_translated_trees(outfname, translation_pairs=None, translation_fcn=None, infname=None, intrees=None):  # specify one of <infname> (nwk file) or <intrees> (list of dendro trees), and one of <translation_pairs>, <translation_fcn>
    # ----------------------------------------------------------------------------------------
    def trnprs(dtree):
        if translation_pairs is None:
            return [(n.taxon.label, translation_fcn(n.taxon.label)) for n in dtree.preorder_node_iter() if n.taxon is not None]
        else:
            return translation_pairs
    # ----------------------------------------------------------------------------------------
    if [infname, intrees].count(None) != 1:
        raise Exception('have to specify exactly one of <infname>, <intrees>, but got %s %s' % (infname, intrees))
    if [translation_pairs, translation_fcn].count(None) != 1:
        raise Exception('have to specify exactly one of <translation_pairs>, <translation_fcn>, but got %s %s' % (infname, intrees))
    if intrees is None:
        assert infname is not None
        intrees = [get_dendro_tree(treestr=s) for s in get_treestrs_from_file(infname)]
    outtrees = []
    for dtree in intrees:
        translate_labels(dtree, trnprs(dtree)) #, debug=True)
        outtrees.append(dtree)
    utils.mkdir(outfname, isfile=True)
    with open(outfname, 'w') as tfile:
        for dtree in outtrees:
            tfile.write(as_str(dtree) + '\n')

# ----------------------------------------------------------------------------------------
def get_mean_leaf_height(tree=None, treestr=None):
    assert tree is None or treestr is None
    if tree is None:
        tree = get_dendro_tree(treestr=treestr, schema='newick')
    heights = get_leaf_depths(tree).values()
    return sum(heights) / len(heights)

# ----------------------------------------------------------------------------------------
def get_ascii_tree(dendro_tree=None, treestr=None, treefname=None, extra_str='', width=200, schema='newick', label_fcn=None):
    """
        AsciiTreePlot docs (don't show up in as_ascii_plot()):
            plot_metric : str
                A string which specifies how branches should be scaled, one of:
                'age' (distance from tips), 'depth' (distance from root),
                'level' (number of branches from root) or 'length' (edge
                length/weights).
            show_internal_node_labels : bool
                Whether or not to write out internal node labels.
            leaf_spacing_factor : int
                Positive integer: number of rows between each leaf.
            width : int
                Force a particular display width, in terms of number of columns.
            node_label_compose_fn : function object
                A function that takes a Node object as an argument and returns
                the string to be used to display it.
    """
    if dendro_tree is None:
        assert treestr is None or treefname is None
        if treestr is None:
            treestr = get_treestr_from_file(treefname)
        dendro_tree = get_dendro_tree(treestr=treestr, schema=schema)
    if get_mean_leaf_height(dendro_tree) == 0.:  # we really want the max height, but since we only care whether it's zero or not this is the same
        return '%szero height' % extra_str
    # elif: get_n_nodes(dendro_tree) > 1:  # not sure if I really need this if any more (it used to be for one-leaf trees (and then for one-node trees), but the following code (that used to be indented) seems to be working fine on one-leaf, one-node, and lots-of-node trees a.t.m.)

    start_char, end_char = '', ''
    def compose_fcn(x):
        if x.taxon is not None:  # if there's a taxon defined, use its label
            lb = x.taxon.label
        elif x.label is not None:  # use node label
            lb = x.label
        else:
            lb = 'o'
        if label_fcn is not None:
            lb = label_fcn(lb)
        return '%s%s%s' % (start_char, lb, end_char)
    dendro_str = dendro_tree.as_ascii_plot(width=width, plot_metric='length', show_internal_node_labels=True, node_label_compose_fn=compose_fcn)
    special_chars = [c for c in reversed(string.punctuation) if c not in set(dendro_str)]  # find some special characters that we can use to identify the start and end of each label (could also use non-printable special characters, but it shouldn't be necessary)
    if len(special_chars) >= 2:  # can't color them directly, since dendropy counts the color characters as printable
        start_char, end_char = special_chars[:2]  # NOTE the colors get screwed up when dendropy overlaps labels (or sometimes just straight up strips stuff), which it does when it runs out of space
        dendro_str = dendro_tree.as_ascii_plot(width=width, plot_metric='length', show_internal_node_labels=True, node_label_compose_fn=compose_fcn)  # call again after modiying compose fcn (kind of wasteful to call it twice, but it shouldn't make a difference)
        dendro_str = dendro_str.replace(start_char, utils.Colors['blue']).replace(end_char, utils.Colors['end'] + '  ')
    else:
        print '  %s can\'t color tree, no available special characters in get_ascii_tree()' % utils.color('red', 'note:')
    if get_n_nodes(dendro_tree) == 1:
        extra_str += ' (one node)'
    return_lines = [('%s%s' % (extra_str, line)) for line in dendro_str.split('\n')]
    return '\n'.join(return_lines)

# ----------------------------------------------------------------------------------------
def rescale_tree(new_mean_height, dtree=None, treestr=None, debug=False):
    # NOTE if you pass in <dtree>, it gets modified, but if you pass in <treestr> you get back a new dtree (which is kind of a dumb way to set this up, but I don't want to change it now. Although I guess it returns None if you pass <dtree>, so you shouldn't get in too much trouble)
    # TODO (maybe) switch calls of this to dendro's scale_edges() (but note you'd then have to get the mean depth beforehand, since that just multiplies by factor, whereas this rescales to get a particular new height)
    """ rescale the branch lengths in dtree/treestr by a factor such that the new mean height is <new_mean_height> """
    if dtree is None:
        dtree = get_dendro_tree(treestr=treestr, suppress_internal_node_taxa=True)
    mean_height = get_mean_leaf_height(tree=dtree)
    if debug:
        print '  current mean: %.4f   target height: %.4f' % (mean_height, new_mean_height)
    for edge in dtree.postorder_edge_iter():
        if edge.head_node is dtree.seed_node:  # why tf does the root node have an edge where it's the child?
            continue
        if debug:
            print '     %5s  %7e  -->  %7e' % (edge.head_node.taxon.label if edge.head_node.taxon is not None else 'None', edge.length, edge.length * new_mean_height / mean_height)
        if mean_height != 0:  # ok should really probably just return without doing anything if every leaf height is zero, but oh well for now
            edge.length *= new_mean_height / mean_height  # rescale every branch length in the tree by the ratio of desired to existing height (everybody's heights should be the same... but they never quite were when I was using Bio.Phylo, so, uh. yeah, uh. not sure what to do, but this is fine. It's checked below, anyway)
    if not treestr:  # i'm really pretty sure there's no point in doing this if we're just going to immediately convert to string (and it just caused huge fucking problems because it was missing the suppress unifurcations arg. I'm so *!$@(($@ing tired of that shit this is like the fourth time I've wasted hours chasing down weirdness that stems from that)
        dtree.update_bipartitions(suppress_unifurcations=False)  # probably doesn't really need to be done
    if debug:
        print '    final mean: %.4f' % get_mean_leaf_height(tree=dtree)
    if treestr:
        return dtree.as_string(schema='newick').strip()

# ----------------------------------------------------------------------------------------
def get_tree_difference_metrics(region, in_treestr, leafseqs, naive_seq):
    taxon_namespace = dendropy.TaxonNamespace()  # in order to compare two trees with the metrics below, the trees have to have the same taxon namespace
    in_dtree = get_dendro_tree(treestr=in_treestr, taxon_namespace=taxon_namespace, suppress_internal_node_taxa=True)
    seqfos = [{'name' : 't%d' % (iseq + 1), 'seq' : seq} for iseq, seq in enumerate(leafseqs)]
    out_dtree = get_fasttree_tree(seqfos, naive_seq=naive_seq, taxon_namespace=taxon_namespace, suppress_internal_node_taxa=True)
    in_height = get_mean_leaf_height(tree=in_dtree)
    out_height = get_mean_leaf_height(tree=out_dtree)
    base_width = 100
    in_ascii_str = get_ascii_tree(dendro_tree=in_dtree, extra_str='      ', width=base_width)  # make copies before the following functions mess the trees up
    out_ascii_str = get_ascii_tree(dendro_tree=out_dtree, extra_str='        ', width=int(base_width*out_height/in_height))
    print '  comparing input and bppseqgen output trees:'
    print '                   heights: %.3f   %.3f' % (in_height, out_height)
    print '      symmetric difference: %d' % dendropy.calculate.treecompare.symmetric_difference(in_dtree, out_dtree)  # WARNING these functions modify the tree (i think by removing unifurcations) becuase OF COURSE THEY DO, wtf
    print '        euclidean distance: %f' % dendropy.calculate.treecompare.euclidean_distance(in_dtree, out_dtree)
    print '              r-f distance: %f' % dendropy.calculate.treecompare.robinson_foulds_distance(in_dtree, out_dtree)
    print '    %s' % utils.color('blue', 'input:')
    print in_ascii_str
    print '    %s' % utils.color('blue', 'output:')
    print out_ascii_str

# ----------------------------------------------------------------------------------------
# loops over uids in <hline> and <lline> (which, in order, must correspond to each other), chooses a new joint uid and applies it to both h and l trees, then checks to make sure the trees are identical
def merge_heavy_light_trees(hline, lline, use_identical_uids=False, check_trees=True, debug=False):
    def ladd(uid, locus):
        return '%s-%s' % (uid, locus)
    def lrm(uid, locus):
        assert '-' in uid and uid.split('-')[-1] == locus
        return uid.replace('-%s' % locus, '')
    if debug:
        print '    before:'
        print '      heavy:'
        print utils.pad_lines(get_ascii_tree(treestr=hline['tree']))
        print '      light:'
        print utils.pad_lines(get_ascii_tree(treestr=lline['tree']))

    if 'heavy-chain-correlation-info' in lline:  # if doing paired h/l correlations, we need to make sure we're pairing togethether the same events here that were used to determine the correlations (they got out of sync before because things got out of order when writing/reading events from subprocesses)
        assert hline['unique_ids'] == lline['heavy-chain-correlation-info']['heavy-chain-uids']
    assert len(hline['unique_ids']) == len(lline['unique_ids'])
    lpair = [hline, lline]
    joint_reco_id = utils.uidhashstr(hline['reco_id'] + lline['reco_id'])
    for ltmp in lpair:
        ltmp['reco_id'] = joint_reco_id
        ltmp['paired-uids'] = []
    dtrees = [get_dendro_tree(treestr=l['tree']) for l in lpair]
    for iuid, (huid, luid) in enumerate(zip(hline['unique_ids'], lline['unique_ids'])):
        joint_uid = utils.uidhashstr(huid + luid)
        for ltmp in lpair:
            ltmp['unique_ids'][iuid] = joint_uid
            if not use_identical_uids:
                ltmp['unique_ids'][iuid] = ladd(ltmp['unique_ids'][iuid], ltmp['loci'][iuid])
        for l1, l2 in zip(lpair, reversed(lpair)):
            l1['paired-uids'].append([l2['unique_ids'][iuid]])
        for dt, uid, ltmp in zip(dtrees, [huid, luid], lpair):  # NOTE huid and luid here are the *old* ones
            dt.find_node_with_taxon_label(uid).taxon = dendropy.Taxon(ltmp['unique_ids'][iuid])  # don't need to update the taxon namespace since we don't use it afterward

    hline['tree'], lline['tree'] = [as_str(dt) for dt in dtrees]  # have to make a separate tree to actually put in the <line>s, since the symmetric difference function screws up the tree

    if check_trees:
        if not use_identical_uids:  # reset back to the plain <joint_uid> so we can compare
            for dt, ltmp in zip(dtrees, lpair):
                for uid, locus in zip(ltmp['unique_ids'], ltmp['loci']):  # yes, they all have the same locus, but see note in utils
                    dt.find_node_with_taxon_label(uid).taxon = dendropy.Taxon(lrm(uid, locus))  # don't need to update the taxon namespace since we don't use it afterward
        tns = dendropy.TaxonNamespace()
        dtrees = [cycle_through_ascii_conversion(dtree=dt, taxon_namespace=tns) for dt in dtrees]  # have to recreate from str before calculating symmetric difference to avoid the taxon namespace being screwed up (I tried a bunch to avoid this, I don't know what it's changing, the tns looks fine, but something's wrong)
        sym_diff = dendropy.calculate.treecompare.symmetric_difference(*dtrees)  # WARNING this function modifies the tree (i think by removing unifurcations) becuase OF COURSE THEY DO, wtf
        if sym_diff != 0:  # i guess in principle we could turn this off after we've run a fair bit, but it seems really dangerous, since if the heavy and light trees get out of sync the whole simulation is ruined
            raise Exception('trees differ (symmetric difference %d) for heavy and light chains' % sym_diff)

    if debug:
        print '    after:'
        print '      symmetric difference: %d' % sym_diff
        print '      heavy:'
        print utils.pad_lines(get_ascii_tree(treestr=hline['tree']))
        print '      light:'
        print utils.pad_lines(get_ascii_tree(treestr=lline['tree']))

# ----------------------------------------------------------------------------------------
def collapse_zero_length_leaves(dtree, sequence_uids, debug=False):  # <sequence_uids> is uids for which we have actual sequences (i.e. not internal nodes inferred by the tree program without sequences)
    if debug > 1:
        print '  merging trivially-dangling leaves into parent internal nodes'
        print '           distance       leaf                     parent'
    removed_nodes = []
    for leaf in list(dtree.leaf_node_iter()):  # subsume super short/zero length leaves into their parent internal nodes
        recursed = False
# TODO this shouldn't really use typical_bcr_seq_len any more since we have h seqs, l seqs, and h+l seqs
        while leaf.edge_length is not None and leaf.edge_length < 1./(2*typical_bcr_seq_len):  # if distance corresponds to less than one mutation, it's probably (always?) just fasttree dangling an internal node as a leaf
            if leaf.parent_node is None:  # why tf can i get the root node here?
                break
            if leaf.parent_node.taxon is not None and leaf.parent_node.taxon.label in sequence_uids:  # only want to do it if the parent node is a (spurious) internal node added by fasttree (this parent's taxon will be None if suppress_internal_node_taxa was set)
                break
            if debug > 1:
                print '            %8.5f      %-20s    %-20s' % (leaf.edge_length, ' " ' if recursed else leaf.taxon.label, 'none' if leaf.parent_node.taxon is None else leaf.parent_node.taxon.label)

            parent_node = leaf.parent_node
            removed_nodes.append(parent_node.taxon.label if parent_node.taxon is not None else None)
            collapse_nodes(dtree, leaf.taxon.label, None, keep_name_node=leaf, remove_name_node=leaf.parent_node)
            leaf = parent_node
            recursed = True
    dtree.update_bipartitions(suppress_unifurcations=False)
    dtree.purge_taxon_namespace()
    if debug:
        print '    merged %d trivially-dangling leaves into parent internal nodes: %s' % (len(removed_nodes), ' '.join(str(n) for n in removed_nodes))
        # print get_ascii_tree(dendro_tree=dtree, extra_str='      ', width=350)
        # print dtree.as_string(schema='newick').strip()

# ----------------------------------------------------------------------------------------
def get_fasttree_tree(seqfos, naive_seq=None, naive_seq_name='XnaiveX', taxon_namespace=None, suppress_internal_node_taxa=False, debug=False):
    if debug:
        print '    running FastTree on %d sequences plus a naive' % len(seqfos)
    uid_list = [sfo['name'] for sfo in seqfos]
    if any(uid_list.count(u) > 1 for u in uid_list):
        raise Exception('duplicate uid(s) in seqfos for FastTree, which\'ll make it crash: %s' % ' '.join(u for u in uid_list if uid_list.count(u) > 1))
    with tempfile.NamedTemporaryFile() as tmpfile:
        if naive_seq is not None:
            tmpfile.write('>%s\n%s\n' % (naive_seq_name, naive_seq))
        for sfo in seqfos:
            tmpfile.write('>%s\n%s\n' % (sfo['name'], sfo['seq']))  # NOTE the order of the leaves/names is checked when reading bppseqgen output
        tmpfile.flush()  # BEWARE if you forget this you are fucked
        with open(os.devnull, 'w') as fnull:
            treestr = subprocess.check_output('./bin/FastTree -gtr -nt ' + tmpfile.name, shell=True, stderr=fnull)
    if debug:
        print '      converting FastTree newick string to dendro tree'
    dtree = get_dendro_tree(treestr=treestr, taxon_namespace=taxon_namespace, ignore_existing_internal_node_labels=not suppress_internal_node_taxa, suppress_internal_node_taxa=suppress_internal_node_taxa, debug=debug)
    naive_node = dtree.find_node_with_taxon_label(naive_seq_name)
    if naive_node is not None:
        dtree.reroot_at_node(naive_node, suppress_unifurcations=False, update_bipartitions=True)

    if not suppress_internal_node_taxa:  # if we *are* suppressing internal node taxa, we're probably calling this from clusterpath, in which case we need to mess with the internal nodes in a way that assumes they can be ignored (so we collapse zero length leaves afterwards)
        collapse_zero_length_leaves(dtree, uid_list + [naive_seq_name], debug=debug)

    return dtree

# ----------------------------------------------------------------------------------------
def node_mtpy(multifo, node):  # number of reads/contigs/whatever (depending on context) with the same sequence
    if multifo is None or node.taxon.label not in multifo or multifo[node.taxon.label] is None:  # most all of them should be in there, but for instance I'm not adding the dummy branch nodes
        return 1
    return multifo[node.taxon.label]

# ----------------------------------------------------------------------------------------
# copied from https://github.com/nextstrain/augur/blob/master/base/scores.py
# also see explanation here https://photos.app.goo.gl/gtjQziD8BLATQivR6
def set_lb_values(dtree, tau, seq_len, metrics_to_calc=None, dont_normalize=False, multifo=None, use_old_multiplicity_method=False, debug=False):
    """
    traverses <dtree> in postorder and preorder to calculate the up and downstream tree length exponentially weighted by distance, then adds them as LBI (and divides as LBR)
    use_old_multiplicity_method: insert multiplicity into integrals (below), which is equivalent to adding N-1 branches between the node and its parent
    new version: add N-1 dummy branches of length <tau> from the node
    """
    getmulti = node_mtpy if use_old_multiplicity_method else lambda x, y: 1

    if debug:
        print '    setting %s values with tau %.4f' % (' and '.join(metrics_to_calc), tau)

    initial_labels = set([n.taxon.label for n in dtree.preorder_node_iter()])
    dtree, dummy_labels = get_tree_with_dummy_branches(dtree, tau, add_dummy_multiplicity_nubs=not use_old_multiplicity_method, multifo=multifo)  # this returns a new dtree, but the old tree is a subtree of the new one (or at least its collection of nodes are), and these nodes get modified by the process (hence the reversal fcn below)

    # calculate clock length (i.e. for each node, the distance to that node's parent)
    for node in dtree.postorder_node_iter():  # postorder vs preorder doesn't matter, but I have to choose one
        if node.parent_node is None:  # root node
            node.clock_length = 0.
        for child in node.child_node_iter():
            child.clock_length = child.distance_from_root() - node.distance_from_root()

    # lbi is the sum of <node.down_polarizer> (downward message from <node>'s parent) and its children's up_polarizers (upward messages)

    # traverse the tree in postorder (children first) to calculate message to parents (i.e. node.up_polarizer)
    for node in dtree.postorder_node_iter():
        node.down_polarizer = 0  # used for <node>'s lbi (this probabably shouldn't be initialized here, since it gets reset in the next loop [at least I think they all do])
        node.up_polarizer = 0  # used for <node>'s parent's lbi (but not <node>'s lbi)
        for child in node.child_node_iter():
            node.up_polarizer += child.up_polarizer
        bl = node.clock_length / tau
        node.up_polarizer *= numpy.exp(-bl)  # sum of child <up_polarizer>s weighted by an exponential decayed by the distance to <node>'s parent
        node.up_polarizer += getmulti(multifo, node) * tau * (1 - numpy.exp(-bl))  # add the actual contribution (to <node>'s parent's lbi) of <node>: zero if the two are very close, increasing toward asymptote of <tau> for distances near 1/tau (integral from 0 to l of decaying exponential)

    # traverse the tree in preorder (parents first) to calculate message to children (i.e. child1.down_polarizer)
    for node in dtree.preorder_internal_node_iter():
        for child1 in node.child_node_iter():  # calculate down_polarizer for each of <node>'s children
            child1.down_polarizer = node.down_polarizer  # first sum <node>'s down_polarizer...
            for child2 in node.child_node_iter():  # and the *up* polarizers of any other children of <node>
                if child1 != child2:
                    child1.down_polarizer += child2.up_polarizer  # add the contribution of <child2> to its parent's (<node>'s) lbi (i.e. <child2>'s contribution to the lbi of its *siblings*)
            bl = child1.clock_length / tau
            child1.down_polarizer *= numpy.exp(-bl)  # and decay the previous sum by distance between <child1> and its parent (<node>)
            child1.down_polarizer += getmulti(multifo, child1) * tau * (1 - numpy.exp(-bl))  # add contribution of <child1> to its own lbi: zero if it's very close to <node>, increasing to max of <tau> (integral from 0 to l of decaying exponential)

    returnfo = {m : {} for m in metrics_to_calc}
    # go over all nodes and calculate lb metrics (can be done in any order)
    total_length = dtree.length()
    for node in dtree.postorder_node_iter():
        vals = {'lbi' : node.down_polarizer, 'lbr' : 0., 'lbf' : 0.}
        for child in node.child_node_iter():
            for mtmp in vals:
                vals[mtmp] += child.up_polarizer
        if node.down_polarizer > 0.:
            vals['lbr'] /= node.down_polarizer  # it might make more sense to not include the branch between <node> and its parent in either the numerator or denominator (here it's included in the denominator), but this way I don't have to change any of the calculations above
        vals['lbf'] *= 100. / total_length

        if dummy_str in node.taxon.label:
            continue
        if node is dtree.seed_node or node.parent_node is dtree.seed_node:  # second clause is only because of dummy root addition (well, and if we are adding dummy root the first clause doesn't do anything)
            vals['lbr'] = 0.
        for metric in metrics_to_calc:
            mval = float(vals[metric])
            if metric == 'lbi' and not dont_normalize:
                assert seq_len is not None
                mval = normalize_lb_val(metric, mval, tau, seq_len)
            returnfo[metric][node.taxon.label] = mval

    if debug:
        # ----------------------------------------------------------------------------------------
        def lbs(node, mtr):
            lstr = '%8.3f' % returnfo[mtr][node.taxon.label]
            if mtr == 'lbr':
                lstr += ' = %-5.3f / %-5.3f' % (returnfo[mtr][node.taxon.label] * node.down_polarizer, node.down_polarizer)
            elif mtr == 'lbf':
                lstr += ' = %-5.3f / %-5.3f' % (returnfo[mtr][node.taxon.label] * total_length, total_length)
            return lstr
        # ----------------------------------------------------------------------------------------
        max_width = str(max([len(n.taxon.label) for n in dtree.postorder_node_iter()]))
        print ('   %s      %s      multi') % (utils.wfmt('node', max_width), ''.join('%s'%utils.wfmt(m, 24 if m in ['lbr', 'lbf'] else 9, jfmt='-') for m in metrics_to_calc)) #, 16*' ' if 'lbr' in metrics_to_calc else '')
        for node in dtree.preorder_node_iter():
            if dummy_str in node.taxon.label:
                continue
            multi_str = ''
            if multifo is not None:
                multi_str = str(node_mtpy(multifo, node))
                if node_mtpy(multifo, node) > 1:
                    multi_str = utils.color('blue', multi_str, width=3)
            lbstrs = [lbs(node, m) for m in metrics_to_calc]
            print ('    %' + max_width + 's  %s    %3s') % (node.taxon.label, ''.join(lbstrs), multi_str)

    # this is maybe time consuming, but I want to leave the tree that was passed in as unmodified as I can (especially since I have to run this fcn twice for lbi/lbr since they need different tau values)
    for node in dtree.postorder_node_iter():
        delattr(node, 'clock_length')
        delattr(node, 'up_polarizer')
        delattr(node, 'down_polarizer')

    remove_dummy_branches(dtree, initial_labels, dummy_labels)

    return returnfo

# ----------------------------------------------------------------------------------------
def get_tree_with_dummy_branches(old_dtree, tau, n_tau_lengths=10, add_dummy_leaves=False, add_dummy_multiplicity_nubs=False, multifo=None, debug=False): # add long branches above root and/or below each leaf, since otherwise we're assuming that (e.g.) leaf node fitness is zero
    # commenting this since I'm pretty sure I've fixed it, but not removing it since if a similar problem surfaces with dummy branch addition, deep copying is an easy way out
    # zero_length_edges = [e for e in old_dtree.preorder_edge_iter() if e.length == 0 and not e.head_node.is_leaf()]
    # if len(zero_length_edges) > 0:  # rerooting to remove dummy branches screws up the tree in some cases with zero length branches (see comment in that fcn)
    #     old_dtree = copy.deepcopy(old_dtree)  # could maybe do this by default, but it'll probably be really slow on large trees (at least iterating through the trees is; although I suppose maybe deepcopy is smater than that)
    #     print '    %s found %d zero length branches in tree, so deep copying before adding dummy branches (this is probably ok ish, but in general it\'s a bad idea to have zero length branches in your trees): %s' % (utils.color('yellow', 'warning'), len(zero_length_edges), ' '.join([e.head_node.taxon.label for e in zero_length_edges]))

    dummy_edge_length = n_tau_lengths * tau

    dummy_labels = []

    new_root_taxon = dendropy.Taxon(dummy_str + '-root')
    old_dtree.taxon_namespace.add_taxon(new_root_taxon)
    new_root_node = dendropy.Node(taxon=new_root_taxon)
    new_dtree = dendropy.Tree(seed_node=new_root_node, taxon_namespace=old_dtree.taxon_namespace, is_rooted=True)
    dummy_labels.append(new_root_node.taxon.label)

    # then add the entire old tree under this new tree
    new_root_node.add_child(old_dtree.seed_node)
    for edge in new_root_node.child_edge_iter():
        edge.length = dummy_edge_length

    if add_dummy_leaves:  # add dummy child branches to each leaf
        tns = new_dtree.taxon_namespace
        for lnode in new_dtree.leaf_node_iter():
            new_label = '%s-%s' % (dummy_str, lnode.taxon.label)
            tns.add_taxon(dendropy.Taxon(new_label))
            new_child_node = lnode.new_child(taxon=tns.get_taxon(new_label), edge_length=dummy_edge_length)
            dummy_labels.append(new_child_node.taxon.label)

    if add_dummy_multiplicity_nubs:  # new way of incorporating multiplicity: add N-1 dummy branches from the node
        tns = new_dtree.taxon_namespace
        for mnode in list(new_dtree.preorder_node_iter()):  # list() is because we're adding nodes as we iterate
            for idum in range(1, node_mtpy(multifo, mnode)):
                new_label = '%s-multi-%d-%s' % (dummy_str, idum, mnode.taxon.label)
                tns.add_taxon(dendropy.Taxon(new_label))
                new_child_node = mnode.new_child(taxon=tns.get_taxon(new_label), edge_length=tau)
                dummy_labels.append(new_child_node.taxon.label)

    # TODO commenting this because it gets triggered way too much, but I'm not actually sure that I can really just ignore the problem (but maybe I can)
    # zero_len_edge_nodes = [e.head_node for n in new_dtree.preorder_node_iter() for e in n.child_edge_iter() if e.length == 0 and not e.head_node.is_leaf()]  # zero len edges above leaves are fine, since leaves don't count for lbr
    # if len(zero_len_edge_nodes) > 0:
    #     print '    %s found %d zero length internal edges in tree, which means lb ratio may mis-categorize branches: %s' % (utils.color('red', 'warning'), len(zero_len_edge_nodes), ' '.join([n.taxon.label for n in zero_len_edge_nodes]))
    #     # for node in zero_len_edge_nodes:  # we don't really want to modify the tree this drastically here (and a.t.m. this causes a crash later on), but I'm leaving it as a placeholder for how to remove zero length edges
    #     #     collapse_nodes(new_dtree, node.taxon.label, node.parent_node.taxon.label)  # keep the child, since it can be a leaf
    #     # print utils.pad_lines(get_ascii_tree(dendro_tree=new_dtree))

    new_dtree.update_bipartitions(suppress_unifurcations=False)  # not sure if I need this? (suppress_unifurcations is because otherwise it removes the branch between the old and new root nodes)

    if debug:
        print '    added dummy branches to tree:'
        print get_ascii_tree(dendro_tree=new_dtree, extra_str='      ', width=350)

    return new_dtree, dummy_labels

# ----------------------------------------------------------------------------------------
def remove_dummy_branches(dtree, initial_labels, dummy_labels, add_dummy_leaves=False, debug=False):
    # if add_dummy_leaves:
    #     print 'UPDATE ok maybe it\'s fine now (since i\'m adding the dummy nubs), but i\'m not checking it'
    #     raise Exception('not implemented (shouldn\'t be too hard, but a.t.m. I don\'t think I\'ll need it)')

    if len(dtree.seed_node.child_nodes()) != 1:
        print '  %s root node has more than one child when removing dummy branches: %s' % (utils.color('yellow', 'warning'), ' '.join([n.taxon.label for n in dtree.seed_node.child_nodes()]))
    new_root_node = dtree.seed_node.child_nodes()[0]
    if debug:
        print '  rerooting at %s' % new_root_node.taxon.label
        print '            current children: %s' % ' '.join([n.taxon.label for n in new_root_node.child_node_iter()])
    # NOTE if the new root has a child separated by a zero-length edge, this reroot call for some reason deletes that child from the tree (both with and without suppress_unifurcations set). After messing around a bunch to try to fix it, the message I'm taking is just that zero length branches (and unifurcations) are a bad idea and I should just forbid them
    # UPDATE I think I was just missing the suppress_unifurcations=False in update_bipartitions(), but leaving these comments here in case there was another problem
    # UPDATE actually the reroot still seems to eat a node sometimes if the tree is unrooted (so adding the extra reroot above)
    # UPDATE this is more or less expectd, from dendropy's perspective; see https://github.com/jeetsukumaran/DendroPy/issues/118
    assert dtree.is_rooted  # make sure it's rooted, to avoid unifurcations getting suppressed (even with the arg set to false)
    dtree.reroot_at_node(new_root_node, suppress_unifurcations=False)  # reroot at old root node
    if debug:
        print '       children after reroot: %s' % ' '.join([n.taxon.label for n in new_root_node.child_node_iter()])
    dtree.prune_taxa_with_labels(dummy_labels, suppress_unifurcations=False)
    dtree.purge_taxon_namespace()  # I'm sure there's a good reason the previous line doesn't do this
    dtree.update_bipartitions(suppress_unifurcations=False)
    if debug:
        print '        children after purge: %s' % ' '.join([n.taxon.label for n in new_root_node.child_node_iter()])

    final_labels = set([n.taxon.label for n in dtree.preorder_node_iter()])
    if initial_labels != final_labels:  # this was only happening with a zero-length node hanging off root (see above), which probably won't happen any more since I'm now removing zero length (non-leaf) branches in bcr-phylo simulator.py
        print '    %s nodes after dummy branch addition and removal not the same as before:' % utils.color('red', 'error')
        print '       missing: %s' % ' '.join(initial_labels - final_labels)
        print '       extra:   %s' % ' '.join(final_labels - initial_labels)
        print '       tree:'
        print utils.pad_lines(get_ascii_tree(dendro_tree=dtree, width=400))
        assert False  # i think it's better to crash at this point, i think i have it working reliably

# ----------------------------------------------------------------------------------------
def get_aa_tree(dtree, annotation, extra_str=None, iclust=None, debug=False):
    very_different_frac = 0.5
    if debug:
        print '    converting nuc tree (mean depth %.3f) to aa' % get_mean_leaf_height(dtree)
        if debug > 1:
            print utils.pad_lines(get_ascii_tree(dendro_tree=dtree, width=400))
        changes = {}

    aa_dtree = copy.deepcopy(dtree)
    nuc_seqs = {uid : seq for uid, seq in zip(annotation['unique_ids'], annotation['seqs'])}
    aa_seqs = {uid : seq for uid, seq in zip(annotation['unique_ids'], annotation['seqs_aa'])}
    if dtree.seed_node.taxon.label not in nuc_seqs and 'naive_seq' in annotation:  # if it's already there, that should be because an observed seq is the root/naive
        nuc_seqs[dtree.seed_node.taxon.label] = annotation['naive_seq']
    if dtree.seed_node.taxon.label not in aa_seqs and 'naive_seq_aa' in annotation:
        aa_seqs[dtree.seed_node.taxon.label] = annotation['naive_seq_aa']  # the aa naive seq *should* always be there now, since I just started adding it in add_seqs_aa()

    n_different, _ = compare_tree_distance_to_shm(dtree, annotation, only_check_leaf_depths=True, iclust=iclust, debug=False)  # this checks leaf depths, whereas in the loop below we check each edge (result should be the ~same, but this fcn has better dbg printing)

    skipped_edges, missing_nodes = [], set()
    if debug > 1:
        print '          N mutations        branch length'
        print '           nuc    aa          nuc      aa       child node'
    for edge in aa_dtree.preorder_edge_iter():
        if edge.tail_node is None:  # edge above root (no, i don't know why root has an edge above it, but that's how it is)
            continue
        cnode = edge.head_node  # child of this edge
        clabel, plabel = cnode.taxon.label, cnode.parent_node.taxon.label  # turns out there's also a .tail_node attribute of the edge that isn't listed properly in the docs
        if clabel not in aa_seqs or plabel not in aa_seqs:  # if either of the seqs are missing, leave the existing (presumably nucleotide-based) branch length unchanged
            skipped_edges.append(edge)
            missing_nodes |= set([clabel, plabel]) - set(aa_seqs)
            continue
        nuc_branch_length = edge.length  # nucleotide distance from parent node (only used for debug, but we have to grab it before we change the edge length)
        aa_mut_frac, aa_n_muts = utils.hamming_fraction(aa_seqs[plabel], aa_seqs[clabel], amino_acid=True, also_return_distance=True)  # should've called it hamming fraction rather than mut frac
        edge.length = aa_mut_frac
        if debug or n_different > 0:
            nuc_mut_frac, nuc_n_muts = utils.hamming_fraction(nuc_seqs[plabel], nuc_seqs[clabel], also_return_distance=True)
            if nuc_mut_frac > 0 and abs(nuc_branch_length - nuc_mut_frac) / nuc_mut_frac > very_different_frac:
                print '          %s nuc branch length %.4f and hamming frac %.4f very different (ratio %.2f) for branch between %s --> %s' % (utils.color('yellow', 'warning'), nuc_branch_length, nuc_mut_frac, nuc_branch_length / nuc_mut_frac, clabel, plabel)
            if debug:
                changes[edge] = (nuc_n_muts, aa_n_muts)
                if debug > 1:
                    print '          %3d   %3d        %.3f     %.3f      %s' % (nuc_n_muts, aa_n_muts, nuc_branch_length, aa_mut_frac, clabel)

    aa_dtree.update_bipartitions(suppress_unifurcations=False)

    if len(skipped_edges) > 0:
        print '      %s get_aa_tree()%s: skipped %d/%d edges for which we didn\'t have sequences for both nodes (i.e. left the original branch length unmodified). Missing nodes: %s' % (utils.color('yellow', 'warning'), '' if extra_str is None else ' %s'%extra_str, len(skipped_edges), len(list(aa_dtree.preorder_edge_iter())), ' '.join(missing_nodes))
    if debug:
        assert len(changes) + len(skipped_edges) + 1 == len(list(aa_dtree.preorder_edge_iter()))  # +1 is for root edge
        print '    rescaled %d/%d edges' % (len(changes), len(list(aa_dtree.preorder_edge_iter())))
        print '      aa tree mean depth: %.3f' % get_mean_leaf_height(aa_dtree)
        n_to_print = 10
        print '       child nodes with %d largest differences between N nuc and N aa changes' % n_to_print
        print '          nuc    aa   parent node    child node'
        for edge in sorted(changes, key=lambda k: changes[k][1] - changes[k][0])[:n_to_print]:
            nuc_n_muts, aa_n_muts = changes[edge]
            print '         %3d    %3d     %-15s %s' % (nuc_n_muts, aa_n_muts, edge.tail_node.taxon.label, edge.head_node.taxon.label)
        if debug > 1:
            print utils.pad_lines(get_ascii_tree(dendro_tree=aa_dtree, width=400))

    return aa_dtree

# ----------------------------------------------------------------------------------------
# check whether 1) node depth and 2) node pairwise distances are super different when calculated with tree vs sequences (not really sure why it's so different sometimes, best guess is fasttree sucks, partly because it doesn't put the root node anywhere near the root of the tree)
def compare_tree_distance_to_shm(dtree, annotation, max_frac_diff=0.25, only_check_leaf_depths=False, extra_str=None, iclust=None, debug=False):  # , min_warn_frac=0.1
    common_nodes = [n for n in dtree.preorder_node_iter() if n.taxon.label in annotation['unique_ids']]
    tdepths, mfreqs, fracs = {}, {}, {}
    for node in common_nodes:
        tdepth = node.distance_from_root()
        mfreq = utils.per_seq_val(annotation, 'mut_freqs', node.taxon.label)
        frac_diff = abs(tdepth - mfreq) / tdepth if tdepth > 0 else 0
        if frac_diff > max_frac_diff:
            key = node.taxon.label
            tdepths[key] = tdepth
            mfreqs[key] = mfreq
            fracs[key] = frac_diff
    if debug or len(fracs) > 0:
        warnstr = utils.color('yellow', 'warning ') if len(fracs) > 0 else ''  # len(fracs) / float(len(common_nodes)) > min_warn_frac else ''
        if debug or warnstr != '':
            print '        %s%stree depth and mfreq differ by more than %.0f%% for %d/%d nodes%s' % ('' if iclust is None else utils.color('blue', 'iclust %d: '%iclust), warnstr if warnstr!='' else utils.color('green', 'ok: '), 100*max_frac_diff, len(fracs), len(common_nodes), '' if extra_str is None else ' for %s' % extra_str)
        if (debug and len(fracs) > 0) or len(fracs) > 0:
            print '    tree depth   mfreq      ratio    frac diff'
            for key, frac in sorted(fracs.items(), key=operator.itemgetter(1), reverse=True):
                print '      %.4f    %.4f     %.4f     %.4f     %s' % (tdepths[key], mfreqs[key], 0 if mfreqs[key]==0 else tdepths[key] / mfreqs[key], frac, key)

    if only_check_leaf_depths:  # the pairwise bit is slow
        return len(fracs), None

    dmatrix = dtree.phylogenetic_distance_matrix()  # note that this only considers leaves
    dmx_taxa = set(dmatrix.taxon_iter())  # phylogenetic_distance_matrix() seems to only return values for leaves, which maybe I'm supposed to expect?
    pv_tdists, pv_mdists, pw_fracs = {}, {}, {}
    for n1, n2 in itertools.combinations([n for n in common_nodes if n.taxon in dmx_taxa], 2):
        tdist = dmatrix.distance(n1.taxon, n2.taxon)
        mdist = utils.hamming_fraction(utils.per_seq_val(annotation, 'seqs', n1.taxon.label), utils.per_seq_val(annotation, 'seqs', n2.taxon.label))
        frac_diff = abs(tdist - mdist) / tdist if tdist > 0 else 0
        if frac_diff > max_frac_diff:
            key = (n1.taxon.label, n2.taxon.label)
            pv_tdists[key] = tdist
            pv_mdists[key] = mdist
            pw_fracs[key] = frac_diff
    if debug or len(pw_fracs) > 0:
        warnstr = utils.color('yellow', 'warning ') if len(pw_fracs) > 0 else ''  #  if len(pw_fracs) / float(len(common_nodes)) > min_warn_frac else ''
        if debug or warnstr != '':
            print '        %s%spairwise distance from tree and sequence differ by more than %.f%% for %d/%d node pairs%s' % ('' if iclust is None else utils.color('blue', 'iclust %d: '%iclust), warnstr if warnstr!='' else utils.color('green', 'ok: '), 100*max_frac_diff, len(pw_fracs), 0.5 * len(common_nodes) * (len(common_nodes)-1), '' if extra_str is None else ' for %s' % extra_str)
        if debug and len(pw_fracs) > 0:
            print '          pairwise'
            print '     tree dist  seq dist    ratio   frac diff'
            for key, frac_diff in sorted(pw_fracs.items(), key=operator.itemgetter(1), reverse=True):
                print '      %.4f     %.4f    %.4f    %.4f    %s  %s' % (pv_tdists[key], pv_mdists[key], pv_tdists[key] / pv_mdists[key], frac_diff, key[0], key[1])

    if debug > 1:
        print utils.pad_lines(get_ascii_tree(dendro_tree=dtree, width=400))
        if 'v_3p_del' in annotation:  # hackey way to avoid trying to print the fake h+l annotation
            utils.print_reco_event(annotation)

    return len(fracs), len(pw_fracs)

# ----------------------------------------------------------------------------------------
def calculate_lb_values(dtree, tau, metrics_to_calc=None, dont_normalize=False, annotation=None, extra_str=None, iclust=None, dbgstr='', debug=False):
    # note that it's a little weird to do all this tree manipulation here, but then do the dummy branch tree manipulation in set_lb_values(), but the dummy branch stuff depends on tau so it's better this way
    # <iclust> is just to give a little more granularity in dbg

    if metrics_to_calc is None:
        metrics_to_calc = lb_metrics.keys()
    else:
        if any(m not in lb_metrics for m in metrics_to_calc):
            raise Exception('unsupported lb metrics in %s (allowed: %s)' % (metrics_to_calc, lb_metrics))

    seq_len = None
    if annotation is not None:
        seq_len = float(numpy.mean([len(s) for s in annotation['seqs']]))  # the numpy type is causing crashes when written to yaml file (yaml.dump is quoting with " instead of ' which breaks something) (although switching to json dump seems to have also fixed it)

    if tau is None:
        if annotation is None:
            raise Exception('need annotation to get sequence lengths if tau is None')
        tau = 1. / seq_len  # note that this uses the nuc seq len even if we're calculating aa lb metrics (which is what we want)
        if iclust is None or iclust == 0:
            print '  setting default tau to 1 / %d = %.4f' % (seq_len, tau)

    if annotation is not None:  # check that the observed shm rate and tree depth are similar (we're still worried that they're different if we don't have the annotation, but we have no way to check it)
        # compare_tree_distance_to_shm(dtree, annotation, extra_str=extra_str, only_check_leaf_depths=True, debug=True)  # this used to be slow (although now we only check depths, avoiding the slow pairwise check), and turning it off for amino acid trees would require some changes, so whatever, leaving it commented for now
        if not utils.is_normed(tau * len(annotation['seqs'][0]), this_eps=0.1):  # should be within 10% at least
            print '  %s inverse of specified tau value %.1f (tau %.4f) not equal to seq len %.1f (inverse %.4f)' % (utils.wrnstr(), 1. / tau, tau, len(annotation['seqs'][0]), 1. / len(annotation['seqs'][0]))

    if max(get_leaf_depths(dtree).values()) > 1:
        if annotation is None:
            raise Exception('tree needs rescaling in lb calculation (metrics will be wrong): found leaf depth greater than 1 (even when less than 1 they can be wrong, but we can be fairly certain that your BCR sequences don\'t have real mutation frequencty greater than 1, so this case we can actually check). If you pass in annotations we can rescale to the observed mutation frequencty.')
        print '  %s leaf depths greater than 1, so rescaling by sequence length' % utils.color('yellow', 'warning')
        dtree.scale_edges(1. / numpy.mean([len(s) for s in annotation['seqs']]))  # using treeutils.rescale_tree() breaks, it seems because the update_bipartitions() call removes nodes near root on unrooted trees

    if debug:
        print '   calculating %s%s with tree:' % (' and '.join(utils.non_none([metrics_to_calc, '?'])), '' if extra_str is None else ' for %s' % extra_str)
        print utils.pad_lines(get_ascii_tree(dendro_tree=dtree, width=400))

    multifo = None
    if annotation is not None:
        multifo = {}  # NOTE now that I'm always doing this, it might make sense to rearrange things a bit, but i don't want to look at it right now
        for node in dtree.postorder_node_iter():
            multifo[node.taxon.label] = utils.get_multiplicity(annotation, uid=node.taxon.label) if node.taxon.label in annotation['unique_ids'] else 1  # if it's not in there, it could be from wonky names from lonr.r, also could be from FastTree tree where we don't get inferred intermediate sequences

    treestr = dtree.as_string(schema='newick')  # get this before the dummy branch stuff to make more sure it isn't modified
    normstr = 'unnormalized' if dont_normalize else 'normalized'

    if iclust is None or iclust == 0:
        print '    calculating %s %s%s with tau %.4f' % (normstr, ' and '.join([lb_metrics.get(m, m) for m in utils.non_none([metrics_to_calc, '?'])]), dbgstr, tau)
    lbvals = set_lb_values(dtree, tau, seq_len, metrics_to_calc=metrics_to_calc, dont_normalize=dont_normalize, multifo=multifo, debug=debug)
    lbvals['tree'] = treestr

    return lbvals

# ----------------------------------------------------------------------------------------
def set_n_generations(seq_len, tau, n_tau_lengths, n_generations, debug=False):
    if n_generations is None:
        assert n_tau_lengths is not None  # have to specify one or the other
        n_generations = max(1, int(seq_len * tau * n_tau_lengths))
        if debug:
            print '       %d generations = seq_len * tau * n_tau_lengths = %d * %.4f * %d = max(1, int(%.2f))' % (n_generations, seq_len, tau, n_tau_lengths, seq_len * tau * n_tau_lengths)
    # else:
    #     if debug:
    #         print '       %d generations' % n_generations
    return n_generations

# ----------------------------------------------------------------------------------------
def get_tree_for_lb_bounds(bound, metric, seq_len, tau, n_generations, n_offspring, debug=False):
    dtree = dendropy.Tree(is_rooted=True)  # note that using a taxon namespace while you build the tree is *much* slower than labeling it afterward (and we do need labels when we calculate lb values)
    if bound == 'min':
        leaf_node = dtree.seed_node  # pretty similar to the dummy root stuff
        for igen in range(n_generations):
            leaf_node = leaf_node.new_child(edge_length=1./seq_len)
    elif bound == 'max':
        old_leaf_nodes = [l for l in dtree.leaf_node_iter()]
        assert len(old_leaf_nodes) == 1
        new_leaf_nodes = []
        for igen in range(n_generations):
            for ileaf in range(len(old_leaf_nodes)):
                for ioff in range(n_offspring):
                    new_leaf_nodes += [old_leaf_nodes[ileaf].new_child(edge_length=1./seq_len)]
            old_leaf_nodes = new_leaf_nodes
            new_leaf_nodes = []
    else:
        assert False

    return dtree

# ----------------------------------------------------------------------------------------
def calculate_lb_bounds(seq_len, tau, n_tau_lengths=10, n_generations=None, n_offspring=2, only_metrics=None, btypes=None, debug=False):  # NOTE the min is just tau, but I don't feel like deleting this fcn just to keep clear what the min means
    info = {m : {} for m in lb_metrics}
    n_generations = set_n_generations(seq_len, tau, n_tau_lengths, n_generations, debug=debug)
    for metric in [m for m in lb_metrics if only_metrics is None or m in only_metrics]:
        for bound in [b for b in ['min', 'max'] if btypes is None or b in btypes]:
            if metric == 'lbr' and bound == 'min':  # lbr min is always zero (leaves)
                info[metric][bound] = {metric : 0., 'vals' : None}
                continue
            if debug:
                print '    %s %s for seq len %d' % (utils.color('red', bound), utils.color('yellow', metric), seq_len)
            start = time.time()
            dtree = get_tree_for_lb_bounds(bound, metric, seq_len, tau, n_generations, n_offspring, debug=debug)
            label_nodes(dtree)
            lbvals = calculate_lb_values(dtree, tau, metrics_to_calc=[metric], dont_normalize=True, debug=debug)
            bfcn = __builtins__[bound]  # min() or max()
            info[metric][bound] = {metric : bfcn(lbvals[metric].values()), 'vals' : lbvals}
            if debug:
                bname, bval = bfcn(lbvals[metric].items(), key=operator.itemgetter(1))
                print '     %s of %d %s values (%.1fs): %s  %.4f' % (bound, len(lbvals[metric]), metric, time.time() - start, bname, bval)

    return info

# ----------------------------------------------------------------------------------------
def find_affy_increases(dtree, line, min_affinity_change=1e-6):
    affy_increasing_edges, affy_changes = [], {}
    for edge in dtree.preorder_edge_iter():
        parent_node = edge.tail_node
        child_node = edge.head_node
        nlist = [parent_node, child_node]
        if None in nlist:
            continue
        parent_affy, child_affy = [utils.per_seq_val(line, 'affinities', n.taxon.label, use_default=True) for n in nlist]
        if None in [parent_affy, child_affy]:
            continue
        daffy = child_affy - parent_affy
        affy_changes[child_node.taxon.label] = daffy
        if daffy > min_affinity_change:
            affy_increasing_edges.append(edge)
    return affy_increasing_edges, affy_changes

# ----------------------------------------------------------------------------------------
def get_n_ancestors_to_affy_increase(affy_increasing_edges, node, dtree, line, n_max_steps=15, also_return_branch_len=False, debug=False):
    if affy_increasing_edges is None:
        affy_increasing_edges, _ = find_affy_increases(dtree, line)
    ancestor_node = node
    chosen_edge = None
    n_steps, branch_len = 0, 0.
    while n_steps < n_max_steps:
        if ancestor_node is dtree.seed_node:
            break
        ancestor_edge = ancestor_node.edge  # edge from current <ancestor_node> to its parent (who in the next line becomes <ancestor_node>)
        ancestor_node = ancestor_node.parent_node  #  move one more step up the tree
        if debug:
            ancestor_uid = ancestor_node.taxon.label
            ancestor_affinity = utils.per_seq_val(line, 'affinities', ancestor_uid, default_val=float('nan'))
        if ancestor_edge in affy_increasing_edges:
            chosen_edge = ancestor_edge
            break
        if debug:
            print '     %12s %5s %12s %2d %8.4f %9.4f   %s' % ('', '', ancestor_uid, n_steps, branch_len, ancestor_affinity, utils.color('yellow', '?') if ancestor_node is dtree.seed_node else '')
        n_steps += 1
        branch_len += ancestor_edge.length

    if chosen_edge is None:
        return (None, None) if also_return_branch_len else None
    if debug:
        print '     %12s %5s %12s %2d %8.4f %9.4f%+9.4f' % ('', '', ancestor_uid, n_steps, branch_len, ancestor_affinity, utils.per_seq_val(line, 'affinities', chosen_edge.head_node.taxon.label, default_val=float('nan')) - ancestor_affinity)  # NOTE the latter can be negative now, since unlike the old fcn (below) we're just looking for an edge where affinity increased (rather than a node with lower affinity than the current one)
    if also_return_branch_len:  # kind of hackey, but we only want the branch length for plotting atm, and actually we aren't even making those plots by default any more
        return n_steps, branch_len
    else:
        return n_steps

# ----------------------------------------------------------------------------------------
def get_n_descendents_to_affy_increase(affy_increasing_edges, node, dtree, line, n_max_steps=15, also_return_branch_len=False, debug=False):
    # ----------------------------------------------------------------------------------------
    def get_branch_length(chosen_edge):  # go back up from the <chosen_edge> to get its total depth from <node> (otherwise we'd need to keep track of the depths for all the child nodes all the way down)
        tedge = chosen_edge
        blen = chosen_edge.length
        while tedge.tail_node is not node:
            tedge = tedge.tail_node.edge
            blen += tedge.length
        return blen
    # ----------------------------------------------------------------------------------------
    child_nodes = [node]
    chosen_edge = None
    n_steps, branch_len  = 1, 0.
    while n_steps < n_max_steps:
        found = False
        child_nodes = [cc for c in child_nodes for cc in c.child_node_iter()]  # all children of current children
        if len(child_nodes) == 0:  # they're all leaves
            break
        for cnode in child_nodes:
            cedge = cnode.edge  # edge to <cnode>'s parent
            if debug:
                child_affinity = utils.per_seq_val(line, 'affinities', cnode.taxon.label, default_val=float('nan'))
            if cedge in affy_increasing_edges:
                chosen_edge = cedge
                found = True
                assert branch_len == 0.
                branch_len = get_branch_length(cedge)
                break
            if debug and not found:
                print '     %12s %5s %12s %2d %8.4f %9.4f  %s' % ('', '', cnode.taxon.label, -n_steps, -get_branch_length(cedge), child_affinity, utils.color('yellow', ' ?') if all(c.is_leaf() for c in child_nodes) else '')
        if found:
            break
        n_steps += 1

    if chosen_edge is None:
        return (None, None) if also_return_branch_len else None
    if debug:
        print '     %12s %5s %12s %+2d %8.4f %9.4f%+9.4f' % ('', '', cnode.taxon.label, -n_steps, -branch_len, child_affinity, child_affinity - utils.per_seq_val(line, 'affinities', chosen_edge.tail_node.taxon.label, default_val=float('nan')))  # NOTE the latter can be negative now, since unlike the old fcn (below) we're just looking for an edge where affinity increased (rather than a node with lower affinity than the current one)
    if also_return_branch_len:  # kind of hackey, but we only want the branch length for plotting atm, and actually we aren't even making those plots by default any more
        return n_steps, branch_len
    else:
        return n_steps

# ----------------------------------------------------------------------------------------
# looks both upwards (positive result) and downwards (negative result) for the nearest edge on which affinity increased from parent to child
def get_min_steps_to_affy_increase(affy_increasing_edges, node, dtree, line, also_return_branch_len=False, lbval=None, only_look_upwards=False, debug=False):
    assert also_return_branch_len
    if debug:
        print '     %12s  %5.3f%12s %2s %8s %9.4f' % (node.taxon.label, lbval, '', '', '', utils.per_seq_val(line, 'affinities', node.taxon.label))
    n_ance, ance_branch_len = get_n_ancestors_to_affy_increase(affy_increasing_edges, node, dtree, line, also_return_branch_len=also_return_branch_len, debug=debug)
    n_desc, desc_branch_len = None, None
    if not only_look_upwards:
        n_desc, desc_branch_len = get_n_descendents_to_affy_increase(affy_increasing_edges, node, dtree, line, also_return_branch_len=also_return_branch_len, debug=debug)
    if n_desc is None and n_ance is None:
        n_steps, blen = None, None
    elif n_desc is None:
        n_steps, blen = n_ance, ance_branch_len
    elif n_ance is None:
        n_steps, blen = -n_desc, -desc_branch_len
    else:  # NOTE only the ancestor one can return zero
        n_steps, blen = (-n_desc, -desc_branch_len) if n_desc < n_ance else (n_ance, ance_branch_len)  # NOTE decides based on N steps, not distance
    if debug:
        if n_steps is None:
            nstr, bstr = [utils.color('yellow', ' ?') for _ in range(2)]
        else:
            nstr = utils.color(('red' if n_steps==0 else 'purple') if n_steps>=0 else 'blue', '%+2d'%n_steps)
            bstr = '%+7.4f' % blen
        print '     %12s %5s %12s %3s  %s' % ('', '', '', nstr, bstr)
    return n_steps, blen

# ----------------------------------------------------------------------------------------
# BELOW: old upward-only fcn. Should be very similar to new ancestor fcn, except that old one looked for affinity increase to <node> whereas new fcn looks for edge on which affinity increase occurred
# ----------------------------------------------------------------------------------------
# NOTE discussion of why we only look upwards in "evaluation framework" section of paper's .tex file (use .tex since there's commented bits)
#  - summary:
#   - Searching only upward reflects the fact that a mutation can only affect the fitness of nodes below it, and thus a high \lbr\ value at a node immediately above an important mutation is likely due to random chance rather than a signal of selection.
#     - EDIT due to random chance OR MAYBE because the super high tau helps/lets the higher node look better since it's nearer to root
#   - Nodes with high \lbr\ that are several steps below such a mutation, on the other hand, simply reflect the fact that increased fitness typically takes several generations to manifest itself as an increase in observed offspring.
#   - In other words searching downward would improve the apparent performance of a metric, but only by counting as successes cases that were successfully predicted only through random chance.
#   - Another reason we do not also search in the downward direction is that in a practical sense it is much more useful to know that the important mutation is above a node than below it.
#   - We could imagine in the lab testing one or a few branches above a node, but because of the bifurcating nature of trees there would be far too many potential branches below (not to mention adding the ambiguity of potentially going up and then down, i.e.\ how to count cousins).
# UPDATE i think the big problem with only looking upwards is that then you don't know what to do with nodes that're above all affinity increases
#  - then it seems reasonable (as below) to just ignore them, which is *bad* since in practice these high nodes will  have really high scores
#  - also, this makes it seem like super large tau is a good idea, since it ignores maybe the big downside to large tau: parents get too much credit for their children's offspring

# def get_n_ancestors_to_affy_change(node, dtree, line, affinity_changes=None, min_affinity_change=1e-6, n_max_steps=15, also_return_branch_len=False, affy_increasing_edges=None, debug=False):
#     debug = True
#     # find number of steps/ancestors to the nearest ancestor with lower affinity than <node>'s
#     #   - also finds the corresponding distance, which is to the lower end of the branch containing the corresponding affinity-increasing mutation
#     #   - this is chosen so that <n_steps> and <branch_len> are both 0 for the node at the bottom of a branch on which affinity increases, and are *not* the distance *to* the lower-affinity node
#     #   - because it's so common for affinity to get worse from ancestor to descendent, it's important to remember that here we are looking for the first ancestor with lower affinity than the node in question, which is *different* to looking for the first ancestor that has lower affinity than one of its immediate descendents (which we could also plot, but it probably wouldn't be significantly different to the metric performance, since for the metric performance we only really care about the left side of the plot, but this only affects the right side)
#     #   - <min_affinity_change> is just to eliminate floating point precision issues (especially since we're deriving affinity by inverting kd) (note that at least for now, and with default settings, the affinity changes should all be pretty similar, and not small)
#     this_affinity = utils.per_seq_val(line, 'affinities', node.taxon.label)
#     if debug:
#         print '     %12s %12s %8s %9.4f' % (node.taxon.label, '', '', this_affinity)

#     ancestor_node = node
#     chosen_ancestor_affinity = None
#     n_steps, branch_len  = 0, 0.
#     while n_steps < n_max_steps:  # note that if we can't find an ancestor with worse affinity, we don't plot the node
#         if ancestor_node is dtree.seed_node:
#             break
#         ancestor_distance = ancestor_node.edge_length  # distance from current <ancestor_node> to its parent (who in the next line becomes <ancestor_node>)
#         ancestor_node = ancestor_node.parent_node  #  move one more step up the tree
#         ancestor_uid = ancestor_node.taxon.label
#         if ancestor_uid not in line['unique_ids']:
#             print '    %s ancestor %s of %s not in true line' % (utils.color('yellow', 'warning'), ancestor_uid, node.taxon.label)
#             break
#         ancestor_affinity = utils.per_seq_val(line, 'affinities', ancestor_uid)
#         if this_affinity - ancestor_affinity > min_affinity_change:  # if we found an ancestor with lower affinity, we're done
#             chosen_ancestor_affinity = ancestor_affinity
#             if affinity_changes is not None:
#                 affinity_changes.append(this_affinity - ancestor_affinity)
#             # if affy_increasing_edges is not None:
#             #     assert any(e in affy_increasing_edges for e in ancestor_node.child_edge_iter())
#             #     # assert ancestor_node.edge in affy_increasing_edges
#             #     print 'OK'
#             break
#         if debug:
#             print '     %12s %12s %8.4f %9.4f%s' % ('', ancestor_uid, branch_len, ancestor_affinity, utils.color('green', ' x') if ancestor_node is dtree.seed_node else '')
#         n_steps += 1
#         branch_len += ancestor_distance

#     if chosen_ancestor_affinity is None:  # couldn't find ancestor with lower affinity
#         return (None, None) if also_return_branch_len else None
#     if debug:
#         print '     %12s %12s %8.4f %9.4f  %s%-9.4f' % ('', ancestor_uid, branch_len, chosen_ancestor_affinity, utils.color('red', '+'), this_affinity - chosen_ancestor_affinity)
#     if also_return_branch_len:  # kind of hackey, but we only want the branch length for plotting atm, and actually we aren't even making those plots by default any more
#         return n_steps, branch_len
#     else:
#         return n_steps

# ----------------------------------------------------------------------------------------
lonr_files = {  # this is kind of ugly, but it's the cleanest way I can think of to have both this code and the R code know what they're called
    'phy.outfname' : 'phy_out.txt',
    'phy.treefname' : 'phy_tree.nwk',
    'outseqs.fname' : 'outseqs.fasta',
    'edgefname' : 'edges.tab',
    'names.fname' : 'names.tab',
    'lonrfname' : 'lonr.csv',
}

# ----------------------------------------------------------------------------------------
def build_lonr_tree(edgefos, debug=False):
    # NOTE have to build the tree from the edge file, since the lonr code seems to add nodes that aren't in the newick file (which is just from phylip).
    all_nodes = set([e['from'] for e in edgefos] + [e['to'] for e in edgefos])
    effective_root_nodes = set([e['from'] for e in edgefos]) - set([e['to'] for e in edgefos])  # "effective" because it can be in an unrooted tree. Not sure if there's always exactly one node that has no inbound edges though
    if len(effective_root_nodes) != 1:
        raise Exception('too many effective root nodes: %s' % effective_root_nodes)
    root_label = list(effective_root_nodes)[0]  # should be '1' for dnapars
    if debug:
        print '      chose \'%s\' as root node' % root_label
    tns = dendropy.TaxonNamespace(all_nodes)
    root_node = dendropy.Node(taxon=tns.get_taxon(root_label))  # NOTE this sets node.label and node.taxon.label to the same thing, which may or may not be what we want  # label=root_label,    (if you start setting the node labels again, you also have to translate them below)
    dtree = dendropy.Tree(taxon_namespace=tns, seed_node=root_node, is_rooted=True)
    remaining_nodes = copy.deepcopy(all_nodes) - set([root_label])  # a.t.m. I'm not actually using <all_nodes> after this, but I still want to keep them separate in case I start using it

    weight_or_distance_key = 'distance'  # maybe should I be using the 'weight' column? I think they're just proportional though so I guess it shouldn't matter (same thing in the line below) # 
    root_edgefos = [efo for efo in edgefos if efo['from'] == root_label]
    for efo in root_edgefos:
        dtree.seed_node.new_child(taxon=tns.get_taxon(efo['to']), edge_length=efo[weight_or_distance_key])  # label=efo['to'],    (if you start setting the node labels again, you also have to translate them below)
        remaining_nodes.remove(efo['to'])

    while len(remaining_nodes) > 0:
        n_removed = 0  # I think I don't need this any more (it only happened before I remembered to remove the root node), but it doesn't seem like it'll hurt)
        for lnode in dtree.leaf_node_iter():
            children = [efo for efo in edgefos if efo['from'] == lnode.taxon.label]
            if debug > 1 and len(children) > 0:
                print '    adding children to %s:' % lnode.taxon.label
            for chfo in children:
                lnode.new_child(taxon=tns.get_taxon(chfo['to']), edge_length=chfo[weight_or_distance_key])  # label=chfo['to'],   (if you start setting the node labels again, you also have to translate them below)
                remaining_nodes.remove(chfo['to'])
                n_removed += 1
                if debug > 1:
                    print '              %s' % chfo['to']
        if debug > 1:
            print '  remaining: %d' % len(remaining_nodes)
        if len(remaining_nodes) > 0 and n_removed == 0:  # if there's zero remaining, we're just about to break anyway
            if debug > 1:
                print '  didn\'t remove any, so breaking: %s' % remaining_nodes
            break

    return dtree

# ----------------------------------------------------------------------------------------
def parse_lonr(outdir, input_seqfos, naive_seq_name, reco_info=None, debug=False):
    def get_node_type_from_name(name, debug=False):  # internal nodes in simulated trees should be labeled like 'mrca-<stuff>' (has to correspond to what bcr-phylo-benchmark did)
        if 'mrca' in name:
            return 'internal'
        elif 'leaf' in name:
            return 'leaf'
        else:
            if debug:
                print '    not sure of node type for \'%s\'' % name
            return None

    # get lonr names (lonr replaces them with shorter versions, I think because of phylip)
    lonr_names, input_names = {}, {}
    with open(outdir + '/' + lonr_files['names.fname']) as namefile:  # headers: "head	head2"
        reader = csv.DictReader(namefile, delimiter='\t')
        for line in reader:
            if line['head'][0] != 'L' and line['head'] != naive_seq_name:  # internal node
                dummy_int = int(line['head'])  # check that it's just a (string of a) number
                assert line['head2'] == '-'
                continue
            input_names[line['head']] = line['head2']  # head2 is our names
            lonr_names[line['head2']] = line['head']

    def final_name(lonr_name):
        return input_names.get(lonr_name, lonr_name)

    # read edge info (i.e., implicitly, the tree that lonr.r used)
    edgefos = []  # headers: "from    to      weight  distance"
    with open(outdir + '/' + lonr_files['edgefname']) as edgefile:
        reader = csv.DictReader(edgefile, delimiter='\t')
        for line in reader:
            line['distance'] = int(line['distance'])
            line['weight'] = float(line['weight'])
            edgefos.append(line)

    dtree = build_lonr_tree(edgefos, debug=debug)

    # switch leaves to input names
    for node in dtree.leaf_node_iter():
        node.taxon.label = input_names[node.taxon.label]
        assert node.label is None  #   (if you start setting the node labels again, you also have to translate them here)
        # node.label = node.taxon.label  #   (if you start setting the node labels again, you also have to translate them here)

    if debug:
        print utils.pad_lines(get_ascii_tree(dendro_tree=dtree, width=250))

    nodefos = {node.taxon.label : {} for node in dtree.postorder_node_iter()}  # info for each node (internal and leaf), destined for output

    # read the sequences for both leaves and inferred (internal) ancestors
    seqfos = {final_name(sfo['name']) : sfo['seq'] for sfo in utils.read_fastx(outdir + '/' + lonr_files['outseqs.fname'])}
    input_seqfo_dict = {sfo['name'] : sfo['seq'] for sfo in input_seqfos}  # just to make sure lonr didn't modify the input sequences
    for node in dtree.postorder_node_iter():
        label = node.taxon.label
        if label not in seqfos:
            raise Exception('unexpected sequence name %s' % label)
        if node.is_leaf() or label == naive_seq_name:
            if label not in input_seqfo_dict:
                raise Exception('leaf node \'%s\' not found in input seqs' % label)
            if seqfos[label] != input_seqfo_dict[label]:
                print 'input: %s' % input_seqfo_dict[label]
                print ' lonr: %s' % utils.color_mutants(input_seqfo_dict[label], seqfos[label], align=True)
                raise Exception('lonr leaf sequence doesn\'t match input sequence (see above)')
        nodefos[label]['seq'] = seqfos[label]

    # read actual lonr info
    lonrfos = []
    if debug:
        print '     pos  mutation   lonr   syn./a.b.d.    parent   child'
    with open(outdir + '/' + lonr_files['lonrfname']) as lonrfile:  # heads: "mutation,LONR,mutation.type,position,father,son,flag"
        reader = csv.DictReader(lonrfile)
        for line in reader:
            assert len(line['mutation']) == 2
            assert line['mutation.type'] in ('S', 'R')
            assert line['flag'] in ('TRUE', 'FALSE')
            mutation = line['mutation'].upper()  # dnapars has it upper case already, but neighbor has it lower case
            parent_name = final_name(line['father'])
            child_name = final_name(line['son'])
            parent_seq = nodefos[parent_name]['seq']
            pos = int(line['position']) - 1  # switch from one- to zero-indexing
            child_seq = nodefos[child_name]['seq']
            if parent_seq[pos] != mutation[0] or child_seq[pos] != mutation[1]:
                print 'parent: %s' % parent_seq
                print ' child: %s' % utils.color_mutants(parent_seq, child_seq, align=True)
                raise Exception('mutation info (%s at %d) doesn\'t match sequences (see above)' % (mutation, pos))

            lonrfos.append({
                'mutation' : mutation,
                'lonr' : float(line['LONR']),
                'synonymous' : line['mutation.type'] == 'S',
                'position' : pos,
                'parent' : parent_name,
                'child' : child_name,
                'affected_by_descendents' : line['flag'] == 'TRUE',
            })
            if debug:
                lfo = lonrfos[-1]
                print '     %3d     %2s     %5.2f     %s / %s        %4s      %-20s' % (lfo['position'], lfo['mutation'], lfo['lonr'], 'x' if lfo['synonymous'] else ' ', 'x' if lfo['affected_by_descendents'] else ' ', lfo['parent'], lfo['child'])

    # check for duplicate nodes (not sure why lonr.r kicks these, but I should probably collapse them at some point)
    # in simulation, we sample internal nodes, but then lonr.r's tree construction forces these to be leaves, but then frequently they're immediately adjacent to internal nodes in lonr.r's tree... so we try to collapse them
    duplicate_groups = utils.group_seqs_by_value(nodefos.keys(), keyfunc=lambda q: nodefos[q]['seq'])
    duplicate_groups = [g for g in duplicate_groups if len(g) > 1]
    if len(duplicate_groups) > 0:
        n_max = 15
        dbg_str = ',  '.join([' '.join(g) for g in duplicate_groups[:n_max]])  # only print the first 15 of 'em, if there's more
        if len(duplicate_groups) > n_max:
            dbg_str += utils.color('blue', ' [...]')
        print '    collapsing %d groups of nodes with duplicate sequences (probably just internal nodes that were renamed by lonr.r): %s' % (len(duplicate_groups), dbg_str)
    for dgroup in duplicate_groups:
        non_phylip_names = [n for n in dgroup if get_node_type_from_name(n) is not None]
        if len(non_phylip_names) == 0:  # and phylip internal node names are of form str(<integer>), so just choose the first alphabetically, because whatever
            name_to_use = sorted(dgroup)[0]
        elif len(non_phylip_names) == 1:
            name_to_use = non_phylip_names[0]
        else:
            raise Exception('wtf %s (should\'ve been either one or zero non-phylip names)' % non_phylip_names)
        names_to_remove = [n for n in dgroup if n != name_to_use]

        for rname in names_to_remove:  # only info in here a.t.m. is the sequence
            del nodefos[rname]
            # NOTE not collapsing nodes in tree to match <nodefos> (see comment on next line)
            # collapse_nodes(dtree, name_to_use, rname, allow_failure=True, debug=True)  # holy fuckballs this is not worth the effort (it doesn't really work because the tree is too screwed up) [just gave up and added the duplicate info to the return dict]

        for lfo in lonrfos:
            for key in ('parent', 'child'):
                if lfo[key] in names_to_remove:
                    lfo[key] = name_to_use

    return {'tree' : dtree.as_string(schema='newick'), 'nodes' : nodefos, 'values' : lonrfos}

# ----------------------------------------------------------------------------------------
def run_lonr(input_seqfos, naive_seq_name, workdir, tree_method, lonr_code_file=None, phylip_treefile=None, phylip_seqfile=None, seed=1, debug=False):
    if lonr_code_file is None:
        lonr_code_file = os.path.dirname(os.path.realpath(__file__)).replace('/python', '/bin/lonr.r')
    if not os.path.exists(lonr_code_file):
        raise Exception('lonr code file %s d.n.e.' % lonr_code_file)
    if tree_method not in ('dnapars', 'neighbor'):
        raise Exception('unexpected lonr tree method %s' % tree_method)

    # # installation stuff
    # rcmds = [
    #     'source("https://bioconductor.org/biocLite.R")',
    #     'biocLite("Biostrings")',
    #     'install.packages("seqinr", repos="http://cran.rstudio.com/")',
    # ]
    # utils.run_r(rcmds, workdir)

    input_seqfile = workdir + '/input-seqs.fa'
    with open(input_seqfile, 'w') as iseqfile:
        for sfo in input_seqfos:
            iseqfile.write('>%s\n%s\n' % (sfo['name'], sfo['seq']))

    existing_phylip_output_str = ''
    if phylip_treefile is not None:  # using existing phylip output, e.g. from cft
        tree = get_dendro_tree(treefname=phylip_treefile)
        edgefos = []
        for node in tree.preorder_node_iter():
            for edge in node.child_edge_iter():
                edgefos.append({'from' : node.taxon.label, 'to' : edge.head_node.taxon.label, 'weight' : edge.length})
        existing_edgefname = workdir + '/edges.csv'
        existing_node_seqfname = workdir + '/infered-node-seqs.fa'
        with open(existing_edgefname, 'w') as edgefile:
            writer = csv.DictWriter(edgefile, ('from', 'to', 'weight'))
            writer.writeheader()
            for line in edgefos:
                writer.writerow(line)
        with open(existing_node_seqfname, 'w') as node_seqfile:
            writer = csv.DictWriter(node_seqfile, ('head', 'seq'))
            writer.writeheader()
            for sfo in utils.read_fastx(phylip_seqfile):
                writer.writerow({'head' : sfo['name'], 'seq' : sfo['seq']})
        existing_phylip_output_str = ', existing.edgefile="%s", existing.node.seqfile="%s"' % (existing_edgefname, existing_node_seqfname)

    rcmds = [
        'source("%s")' % lonr_code_file,
        'set.seed(%d)' % seed,
        'G.phy.outfname = "%s"'  % lonr_files['phy.outfname'],  # this is a pretty shitty way to do this, but the underlying problem is that there's too many files, but I don't want to parse them all into one or two files in R, so I need to pass all of 'em to the calling python script
        'G.phy.treefname = "%s"' % lonr_files['phy.treefname'],
        'G.outseqs.fname = "%s"' % lonr_files['outseqs.fname'],
        'G.edgefname = "%s"'     % lonr_files['edgefname'],
        'G.names.fname = "%s"'   % lonr_files['names.fname'],
        'G.lonrfname = "%s"'     % lonr_files['lonrfname'],
        'compute.LONR(method="%s", infile="%s", workdir="%s/", outgroup="%s"%s)' % (tree_method, input_seqfile, workdir, naive_seq_name, existing_phylip_output_str),
    ]
    outstr, errstr = utils.run_r(rcmds, workdir, extra_str='      ', return_out_err=True, debug=debug)
    if debug:
        print utils.pad_lines(outstr)
        print utils.pad_lines(errstr)

    os.remove(input_seqfile)
    if phylip_treefile is not None:
        os.remove(existing_edgefname)
        os.remove(existing_node_seqfname)

# ----------------------------------------------------------------------------------------
def calculate_liberman_lonr(input_seqfos=None, line=None, reco_info=None, phylip_treefile=None, phylip_seqfile=None, tree_method=None, naive_seq_name='X-naive-X', seed=1, debug=False):
    # NOTE see issues/notes in bin/lonr.r
    if phylip_treefile is not None or phylip_seqfile is not None:
        raise Exception('never got this (passing phylip output files to lonr.r) to work -- lonr.r kept barfing, although if you were running exactly the same phylip commands as lonr.r does, it would probably work.')
    assert input_seqfos is None or line is None
    if input_seqfos is None:
        input_seqfos = [{'name' : line['unique_ids'][iseq], 'seq' : line['seqs'][iseq]} for iseq in range(len(line['unique_ids']))]
        input_seqfos.insert(0, {'name' : naive_seq_name, 'seq' : line['naive_seq']})
    if tree_method is None:
        tree_method = 'dnapars' if len(input_seqfos) < 500 else 'neighbor'

    workdir = utils.choose_random_subdir('/tmp/%s' % os.getenv('USER', default='partis-work'))
    os.makedirs(workdir)

    if debug:
        print '  %s' % utils.color('green', 'lonr:')
    run_lonr(input_seqfos, naive_seq_name, workdir, tree_method, phylip_treefile=phylip_treefile, phylip_seqfile=phylip_seqfile, seed=seed, debug=debug)
    lonr_info = parse_lonr(workdir, input_seqfos, naive_seq_name, reco_info=reco_info, debug=debug)

    for fn in lonr_files.values():
        os.remove(workdir + '/' + fn)
    os.rmdir(workdir)

    return lonr_info

# ----------------------------------------------------------------------------------------
def get_tree_metric_lines(annotations, cpath, reco_info, use_true_clusters, min_overlap_fraction=0.5, only_use_best_partition=False, only_plot_uids_with_affinity_info=False, glfo=None, debug=False):
    # collect inferred and true events
    inf_lines_to_use, true_lines_to_use = None, None
    if use_true_clusters:  # use clusters from the true partition, rather than inferred one
        assert reco_info is not None
        true_partition = utils.get_partition_from_reco_info(reco_info)
        print '    using %d true clusters to calculate inferred selection metrics (sizes: %s)' % (len(true_partition), ' '.join(str(l) for l in sorted([len(c) for c in true_partition], reverse=True)))
        if len(annotations) != len(true_partition):
            print '  %s different length true %d and inferred %d partitions when trying to match up clusters for use_true_clusters' % (utils.wrnstr(), len(true_partition), len(annotations))
        if debug:
            print '      choosing    N        N       N         frac       (N chosen)'
            print '       from     true  & chosen = in common  in common   (w/out duplicates)'
        inf_lines_to_use, true_lines_to_use = [], []
        chosen_ustrs = set()  # now that we're using the fraction instead of the raw total, we mostly shouldn't get multiple true clusters corresponding to the same inferred cluster, but maybe it'll still happen occasionally
        for cluster in true_partition:
            true_lines_to_use.append(utils.synthesize_multi_seq_line_from_reco_info(cluster, reco_info))  # note: duplicates (a tiny bit of) code in utils.print_true_events()
            n_max_in_common, max_frac_in_common, ustr_to_use = None, None, None  # look for the inferred cluster that has the most uids in common with this true cluster
            for ustr in set(annotations) - chosen_ustrs:  # order will be different in reco info and inferred clusters
                n_in_common = len(set(utils.uids_and_dups(annotations[ustr])) & set(cluster))  # can't just look for the actual cluster since we collapse duplicates, but bcr-phylo doesn't (but maybe I should throw them out when parsing bcr-phylo output)
                frac_in_common = n_in_common**2 / float(len(utils.uids_and_dups(annotations[ustr])) * len(cluster))  # and have to use frac instead of total to guard against inferred clusters that include several true clusters (reminder: these inferred clusters may have been run with --n-final-clusters 1 or something similar)
                if max_frac_in_common is None or frac_in_common > max_frac_in_common:
                    ustr_to_use = ustr
                    n_max_in_common = n_in_common
                    max_frac_in_common = frac_in_common
            if max_frac_in_common is None:
                raise Exception('cluster \'%s\' not found in inferred annotations (probably because use_true_clusters was set)' % ':'.join(cluster))
            if max_frac_in_common < min_overlap_fraction:
                raise Exception('overlap fraction %.3f too small: for true cluster (size %d), highest was for inferred cluster with size %d (%d including duplicates). Maybe need to set --simultaneous-true-clonal-seqs (if you did set --simultaneous-true-clonal-seqs, you probably need to set --no-indels, i.e. a true cluster got split apart because of incorrect indel calls).' % (max_frac_in_common, len(cluster), len(annotations[ustr_to_use]['unique_ids']), len(utils.uids_and_dups(annotations[ustr_to_use]))))
            if debug:
                print '      %4d     %4d     %4d     %4d        %4.2f        (%d)' % (len(set(annotations) - chosen_ustrs), len(cluster), len(utils.uids_and_dups(annotations[ustr_to_use])), n_max_in_common, max_frac_in_common, len(annotations[ustr_to_use]['unique_ids']))
            if max_frac_in_common < 1:
                print '            note: couldn\'t find an inferred cluster that corresponded exactly to the true cluster (best was %d & %d = %d (frac %.2f), where the inferred includes %d duplicates)' % (len(utils.uids_and_dups(annotations[ustr_to_use])), len(cluster), n_max_in_common, max_frac_in_common, utils.n_dups(annotations[ustr_to_use]))
            if ustr_to_use in chosen_ustrs:
                raise Exception('chose the same inferred cluster to correspond to two different true clusters')
            chosen_ustrs.add(ustr_to_use)
            inf_lines_to_use.append(annotations[ustr_to_use])
    else:  # use clusters from the inferred partition (whether from <cpath> or <annotations>), and synthesize clusters exactly matching these using single true annotations from <reco_info> (to repeat: these are *not* true clusters)
        inf_lines_to_use = annotations.values()  # we used to restrict it to clusters in the best partition, but I'm switching since I think whenever there are extra ones in <annotations> we always actually want their tree metrics (at the moment there will only be extra ones if either --calculate-alternative-annotations or --write-additional-cluster-annotations are set, but in the future it could also be the default)
        if only_use_best_partition:
            assert cpath is not None and cpath.i_best is not None
            inf_lines_to_use = [l for l in inf_lines_to_use if l['unique_ids'] in cpath.partitions[cpath.i_best]]
        if only_plot_uids_with_affinity_info:
            assert False  # should work fine as is, but needs to be checked and integrated with things
            tmplines = []
            for line in inf_lines_to_use:
                iseqs_to_keep = [i for i, a in enumerate(line['affinities']) if a is not None]
                if len(iseqs_to_keep) == 0:
                    continue
                print '  keeping %d/%d' % (len(iseqs_to_keep), len(line['unique_ids']))
                new_line = copy.deepcopy(line)  # *really* don't want to modify the annotations from partitiondriver
                utils.restrict_to_iseqs(new_line, iseqs_to_keep, glfo)
                tmplines.append(new_line)
            inf_lines_to_use = tmplines
        if reco_info is not None:
            for line in inf_lines_to_use:
                true_line = utils.synthesize_multi_seq_line_from_reco_info(line['unique_ids'], reco_info)
                true_lines_to_use.append(true_line)

    return inf_lines_to_use, true_lines_to_use

# ----------------------------------------------------------------------------------------
def plot_tree_metrics(args, plotdir, metrics_to_calc, antn_list, is_simu=False, inf_annotations=None, ete_path=None, workdir=None, include_relative_affy_plots=False, queries_to_include=None,
                      paired=False, debug=False):
    reqd_args = [('selection_metric_plot_cfg', None), ('slice_bin_fname', None), ('queries_to_include', None), ('label_tree_nodes', False), ('label_root_node', False), ('affinity_key', None)]
    for marg, dval in [(a, v) for a, v in reqd_args if not hasattr(args, a)]:  # "required" args, just so when i add an arg to bin/partis i don't also have to add it to smetric-run.py
        setattr(args, marg, dval)

    assert not include_relative_affy_plots  # would need updating
    import plotting
    import lbplotting
    start = time.time()
    print '           plotting to %s' % plotdir
    if inf_annotations is not None:
        assert is_simu

    plot_cfg = args.selection_metric_plot_cfg
    if plot_cfg is None:
        plot_cfg = all_plot_cfg
    affy_key = 'affinities'
    if args.affinity_key is not None:
        affy_key = args.affinity_key
        tmplines = [l for l in antn_list if args.affinity_key in l]
        if len(tmplines) == 0:
            print '  %s --affinity-key \'%s\' doesn\'t occur in any of the %d annotations' % (utils.wrnstr(), args.affinity_key, len(antn_list))
        for atn in tmplines:
            atn['affinities'] = atn[args.affinity_key]
    has_affinities = any('affinities' in l for l in antn_list)
    if has_affinities and any('affinities' not in l for l in antn_list):  # if at least one has them, but not all of them do, add null values (this is kind of hackey, but it's way way better than handling some, but not all, of the lines missing affinities in all the differeing plotting fcns)
        for atn in [l for l in antn_list if 'affinities' not in l]:
            atn['affinities'] = [None for _ in atn['unique_ids']]
    has_trees = is_simu or any(tk in l['tree-info']['lb'] for l in antn_list for tk in ['tree', 'aa-tree'])
    if is_simu and (not has_affinities or all(affy is None for affy in antn_list[0]['affinities'])):  # if it's bcr-phylo simulation we should have affinities for everybody, otherwise for nobody
        print '      %s no affinity information in this simulation, so can\'t plot lb/affinity' % utils.color('yellow', 'note')
        return

    utils.prep_dir(plotdir, wildlings=['*.svg', '*.html'], allow_other_files=True, subdirs=lb_metrics.keys())
    fnames = lbplotting.add_fn(None, init=True)

    if has_affinities:
        affy_fnames, slice_fnames = [[]], [[]]
        for mtr in [m for m in metrics_to_calc if m in affy_metrics]:
            if 'lb-vs-affy' in plot_cfg:
                lbplotting.plot_lb_vs_affinity(plotdir, antn_list, mtr, only_csv=args.only_csv_plots, fnames=affy_fnames, separate_rows=True, is_true_line=is_simu, affy_key=affy_key, debug=debug)
            if 'slice' in plot_cfg:
                lbplotting.make_lb_vs_affinity_slice_plots(plotdir, antn_list, mtr, only_csv=args.only_csv_plots, fnames=slice_fnames, separate_rows=True, is_true_line=is_simu, paired=paired, n_bin_cfg_fname=args.slice_bin_fname, debug=debug)
            # lbplotting.make_lb_scatter_plots('affinity-ptile', plotdir, mtr, antn_list, yvar=mtr+'-ptile', fnames=fnames, is_true_line=is_simu)
        fnames += [['header', 'affinity metrics']] + affy_fnames + slice_fnames
        if 'joy' in plot_cfg and not args.only_csv_plots:
            fnames.append([])
            for mtr in metrics_to_calc:
                lbplotting.make_lb_affinity_joyplots(plotdir + '/joyplots', antn_list, mtr, fnames=fnames)
        if 'lb-vs-daffy' in plot_cfg:
            daffy_fnames = [[]]
            for mtr in [m for m in metrics_to_calc if m in daffy_metrics]:
                lbplotting.plot_lb_vs_ancestral_delta_affinity(plotdir + '/' + mtr, antn_list, mtr, is_true_line=is_simu, only_csv=args.only_csv_plots, fnames=daffy_fnames, separate_rows=True, debug=debug)
            fnames += [['header', 'delta-affinity metrics']] + daffy_fnames
    if ('distr' in plot_cfg or not has_affinities) and not args.only_csv_plots:
        for mtr in metrics_to_calc:
            lbplotting.plot_lb_distributions(mtr, plotdir, antn_list, is_true_line=is_simu, fnames=fnames, only_overall=False, n_iclust_plot_fnames=None if has_affinities else 8) #, stats='mean:max')
    lbplotting.add_fn(fnames, new_row=True)

    if not args.only_csv_plots:  # all the various scatter plots are really slow
        if 'lb-scatter' in plot_cfg:
            for xv, yv in [(xv, yv) for xv, yv in [('cons-dist-aa', 'aa-lbi'), ('aa-lbi', 'lbi'), ('sum-cons-dist-aa', 'sum-aa-lbi'), ('sum-aa-lbi', 'sum-lbi')] if xv in metrics_to_calc and yv in metrics_to_calc]:
                lbplotting.make_lb_scatter_plots(xv, plotdir, yv, antn_list, fnames=fnames, is_true_line=is_simu, colorvar='affinity' if has_affinities and 'cons-dist' in xv else None, add_jitter='cons-dist' in xv, n_iclust_plot_fnames=None if has_affinities else 8, queries_to_include=args.queries_to_include) #, add_stats='correlation')
        if ete_path is not None and has_trees and 'tree' in plot_cfg:
            lbplotting.plot_lb_trees(metrics_to_calc, plotdir, antn_list, ete_path, workdir, is_true_line=is_simu, queries_to_include=args.queries_to_include, fnames=fnames, label_all_nodes=args.label_tree_nodes, label_root_node=args.label_root_node)
        subdirs = [d for d in os.listdir(plotdir) if os.path.isdir(plotdir + '/' + d)]
        plotting.make_html(plotdir, fnames=fnames, new_table_each_row=True, htmlfname=plotdir + '/overview.html', extra_links=[(subd, '%s/' % subd) for subd in subdirs], bgcolor='#FFFFFF', title='all plots:')

    if is_simu and not args.only_csv_plots and 'true-vs-inf-metrics' in plot_cfg and inf_annotations is not None:
        for mtr in [m for m in metrics_to_calc if m in lb_metrics]:
            lbplotting.plot_true_vs_inferred_lb(plotdir + '/' + mtr, antn_list, inf_annotations, mtr, fnames=fnames)
        lbplotting.plot_cons_seq_accuracy(plotdir, antn_list, fnames=fnames)

    if 'tree-mut-stats' in plot_cfg:
        plotting.plot_tree_mut_stats(plotdir + '/hmm/tree-mut-stats', antn_list, is_simu)  # only_leaves=True

    print '    selection metric plotting time: %.1f sec' % (time.time() - start)

# ----------------------------------------------------------------------------------------
def check_lb_values(line, lbvals):
    for metric in [m for m in lbvals if m in lb_metrics]:
        missing = set(line['unique_ids']) - set(lbvals[metric])
        if len(missing) > 0:  # we expect to get extra ones in the tree, for inferred ancestral nodes for which we don't have sequences, but missing ones probabliy indicate something's up
            # raise Exception('uids in annotation not the same as lb info keys\n    missing: %s\n    extra: %s' % (' '.join(set(line['unique_ids']) - set(lbvals[metric])), ' '.join(set(lbvals[metric]) - set(line['unique_ids']))))
            extra = set(lbvals[metric]) - set(line['unique_ids'])
            common = set(line['unique_ids']) & set(lbvals[metric])
            print '    %s uids in annotation not the same as lb info keys for \'%s\':  %d missing from lb info  %d extra in lb info  (%d in common)'  % (utils.color('red', 'error'), metric, len(missing), len(extra), len(common))
            if len(missing) + len(extra) < 35:
                print '      missing from lb info: %s\n      extra in lb info: %s\n      common: %s' % (' '.join(missing), ' '.join(extra), ' '.join(common))

# ----------------------------------------------------------------------------------------
def check_cluster_indices(cluster_indices, ntot, inf_lines_to_use):
    if cluster_indices is None:
        return
    if min(cluster_indices) < 0 or max(cluster_indices) >= ntot:
        raise Exception('invalid cluster indices %s for partition with %d clusters' % (cluster_indices, ntot))
    print '      skipped all iclusts except %s (size%s %s)' % (' '.join(str(i) for i in cluster_indices), utils.plural(len(cluster_indices)), ' '.join(str(len(inf_lines_to_use[i]['unique_ids'])) for i in cluster_indices))

# ----------------------------------------------------------------------------------------
# gets new tree for each specified annotation, and add a new 'tree-info' key for each (overwriting any that's already there)
def get_trees_for_annotations(inf_lines_to_use, treefname=None, cpath=None, workdir=None, cluster_indices=None, run_gctree=False, gctree_outdir=None, glfo=None, debug=False):
    # ----------------------------------------------------------------------------------------
    def prep_gctree(iclust, line):
        if glfo is not None:  # if you don't pass in glfo, your sequences better not have fwk insertions since gctree barfs on ambiguous bases
            utils.trim_fwk_insertions(glfo, line)  # NOTE maybe will need to reverse this or something?
        assert workdir is not None or gctree_outdir is not None
        subwd = '%s/gctree/iclust-%d' % (utils.non_none([gctree_outdir, workdir]), iclust)
        ifn = '%s/inseqs.fa' % subwd
        ofn = '%s/tree.nwk' % subwd
        naive_name = 'naive'
        utils.mkdir(subwd)
        if os.path.exists(ifn):
            print '    note: not overwriting existing gctree input %s' % ifn
        else:
            utils.write_fasta(ifn, utils.seqfos_from_line(line, add_sfos_for_multiplicity=True, prepend_naive=True, naive_name=naive_name))
        cmdstr = '%s/bin/gctree-run.py --infname %s --outdir %s --root-label %s --inf-int-label i-%d-inf' % (utils.get_partis_dir(), ifn, subwd, naive_name, iclust)
        return {'cmd_str' : cmdstr, 'workdir' : subwd, 'outfname' : ofn, 'workfnames' : [ifn]}
    # ----------------------------------------------------------------------------------------
    def addtree(iclust, line, dtree, origin):
        treefos[iclust] = {'tree' : dtree, 'origin' : origin}
    # ----------------------------------------------------------------------------------------
    ntot = len(inf_lines_to_use)
    print '    getting trees for %d cluster%s with size%s: %s' % (ntot, utils.plural(ntot), utils.plural(ntot), ' '.join(str(len(l['unique_ids'])) for l in inf_lines_to_use))
    filetrees = None
    if treefname is not None:
        filetrees = []
        for treestr in get_treestrs_from_file(treefname):
            dtree = get_dendro_tree(treestr=treestr, debug=False)  # , ignore_existing_internal_node_labels=ignore_existing_internal_node_labels  # maybe i'll need this again in future?
            treeids = set([n.taxon.label for n in dtree.preorder_node_iter()])
            filetrees.append({'tree' : dtree, 'ids' : treeids})
        print '      read %d trees from %s' % (len(filetrees), treefname)
    check_cluster_indices(cluster_indices, ntot, inf_lines_to_use)
    tree_origin_counts = {n : {'count' : 0, 'label' : l} for n, l in (('treefname', 'read from %s' % treefname), ('cpath', 'made from cpath'), ('fasttree', 'ran fasttree'), ('gctree', 'ran gctree'), ('no-uids', 'no uids in common between annotation and trees in file'), ('lonr', 'ran liberman lonr'))}
    n_already_there, n_skipped_uid = 0, 0
    cmdfos, treefos = [None for _ in inf_lines_to_use], [None for _ in inf_lines_to_use]
    for iclust, line in enumerate(inf_lines_to_use):
        if cluster_indices is not None and iclust not in cluster_indices:
            continue
        if debug:
            print '  %s sequence cluster' % utils.color('green', str(len(line['unique_ids'])))
        if 'tree-info' in line:  # overwrite any existing trees (although we could go back to skipping them) NOTE doesn't rerun gctree though if the output files are already there
            if debug:
                print '       %s overwriting tree that was already in <line>' % utils.color('yellow', 'warning')
            n_already_there += 1
        if treefname is not None:  # this assumes all trees are in the file, but i guess we could also just see if some are there and get the others ourselves
            uids_in_common = set()
            for tfo in filetrees:
                uids_in_common = tfo['ids'] & set(line['unique_ids'])
                if len(uids_in_common) > 0:  # take the first one with any in common
                    dtree = tfo['tree']
                    origin = 'treefname'
                    break
            if len(uids_in_common) == 0:
                dtree = None  # can't continue here since we want to increment tree_origin_counts
                origin = 'no-uids'
                print '  %s no uids in common between line and any trees from %s (line ids: %s)' % (utils.wrnstr(), treefname, ' '.join(line['unique_ids']))
        elif False:  # use_liberman_lonr_tree:  # NOTE see issues/notes in bin/lonr.r
            lonr_info = calculate_liberman_lonr(line=line, reco_info=reco_info, debug=debug)
            dtree = get_dendro_tree(treestr=lonr_info['tree'])
            # line['tree-info']['lonr'] = lonr_info
            origin = 'lonr'
        elif run_gctree:
            cmdfos[iclust] = prep_gctree(iclust, line)
            dtree = None
            origin = 'gctree'
        elif cpath is not None and cpath.i_best is not None and line['unique_ids'] in cpath.partitions[cpath.i_best]:
            dtree = cpath.get_single_tree(line, get_fasttrees=True, debug=False)
            origin = 'cpath'
        else:  # NOTE i sunk a bunch of time into trying to parallelize this, but since the existing fcn uses tempfile, and is called from a bunch of other places, it's pretty darn hard and probably not worth it
            seqfos = [{'name' : uid, 'seq' : seq} for uid, seq in zip(line['unique_ids'], line['seqs'])]
            dtree = get_fasttree_tree(seqfos, naive_seq=line['naive_seq'], debug=debug)
            origin = 'fasttree'

        tree_origin_counts[origin]['count'] += 1
        if dtree is None:
            if origin == 'no-uids':
                n_skipped_uid += 1
            continue
        addtree(iclust, line, dtree, origin)

    if cmdfos.count(None) != len(cmdfos):
        start = time.time()
        utils.run_cmds(cmdfos, n_max_procs=utils.auto_n_procs(), proc_limit_str='gctree-run.py', debug='print')
        print '    made %d gctrees (%.1fs)' % (len(cmdfos), time.time() - start)
        assert len(inf_lines_to_use) == len(cmdfos)
        for iclust, (line, cfo) in enumerate(zip(inf_lines_to_use, cmdfos)):
            dtree = get_dendro_tree(treefname=cfo['outfname'])
            seqfos = utils.read_fastx('%s/inferred-seqs.fa'%os.path.dirname(cfo['outfname']), look_for_tuples=True)
            utils.add_seqs_to_line(line, seqfos, glfo, debug=debug)  # ok, i guess you need glfo (see above)
            addtree(iclust, line, dtree, 'gctree')

    print '      tree origins: %s' % ',  '.join(('%d %s' % (nfo['count'], nfo['label'])) for n, nfo in tree_origin_counts.items() if nfo['count'] > 0)
    if n_skipped_uid > 0:
        print '    skipped %d/%d clusters that had no uids in common with tree in %s' % (n_skipped_uid, len(inf_lines_to_use), treefname)
    if n_already_there > 0:
        print '    %s overwriting %d / %d that already had trees' % (utils.color('yellow', 'warning'), n_already_there, ntot)

    return treefos

# ----------------------------------------------------------------------------------------
def get_aa_lb_metrics(line, nuc_dtree, lb_tau, dont_normalize_lbi=False, extra_str=None, iclust=None, debug=False):  # and add them to <line>
    utils.add_seqs_aa(line)
    if max(get_leaf_depths(nuc_dtree).values()) > 1:  # not really sure why i have to add this before converting to aa, but it seems necessary to avoid getting a huge branch below root (and for consistency -- if we're calculating also [nuc-]lbi the nuc tree is already rescaled when we get here
        if line is None:
            raise Exception('tree needs rescaling in lb calculation (metrics will be wrong): found leaf depth greater than 1 (even when less than 1 they can be wrong, but we can be fairly certain that your BCR sequences don\'t have real mutation frequencty greater than 1, so this case we can actually check). If you pass in annotations we can rescale to the observed mutation frequencty.')
        print '  %s leaf depths greater than 1, so rescaling by sequence length' % utils.color('yellow', 'warning')
        nuc_dtree.scale_edges(1. / numpy.mean([len(s) for s in line['seqs']]))  # using treeutils.rescale_tree() breaks, it seems because the update_bipartitions() call removes nodes near root on unrooted trees
    aa_dtree = get_aa_tree(nuc_dtree, line, extra_str=extra_str, iclust=iclust, debug=debug)
    aa_lb_info = calculate_lb_values(aa_dtree, lb_tau, annotation=line, dont_normalize=dont_normalize_lbi, extra_str=extra_str, iclust=iclust, dbgstr=' on aa tree', debug=debug)
    if 'tree-info' not in line:
        line['tree-info'] = {'lb' : {}}
    line['tree-info']['lb']['aa-tree'] = aa_dtree.as_string(schema='newick')
    for nuc_metric in [k for k in aa_lb_info if k != 'tree']:
        line['tree-info']['lb']['aa-'+nuc_metric] = aa_lb_info[nuc_metric]

# ----------------------------------------------------------------------------------------
def add_smetrics(args, metrics_to_calc, annotations, lb_tau, cpath=None, treefname=None, reco_info=None, use_true_clusters=False, base_plotdir=None,
                 train_dtr=False, dtr_cfg=None, ete_path=None, workdir=None, true_lines_to_use=None, outfname=None, only_use_best_partition=False, glfo=None, gctree_outdir=None, debug=False):
    min_cluster_size = args.min_selection_metric_cluster_size  # default_min_selection_metric_cluster_size
    print 'getting selection metrics: %s' % ' '.join(metrics_to_calc)
    if reco_info is not None:
        if not use_true_clusters:
            print '    note: getting selection metrics on simulation without setting <use_true_clusters> (i.e. probably without setting --simultaneous-true-clonal-seqs)'
        for tmpline in reco_info.values():
            assert len(tmpline['unique_ids']) == 1  # at least for the moment, we're splitting apart true multi-seq lines when reading in seqfileopener.py

    if args.dtr_path is not None:
        assert not args.dont_normalize_lbi  # it's trained on normalized lbi, so results are garbage if you don't normalize
        dtr_cfgvals, trainfo, skmodels, pmml_models, missing_models = init_dtr(train_dtr, args.dtr_path, cfg_fname=dtr_cfg)

    if true_lines_to_use is not None:  # being called by bin/smetric-run.py or combine_selection_metrics()
        assert reco_info is None
        inf_lines_to_use = None
    else:  # called from python/partitiondriver.py (with reco_info set, which needs to be turned into true_lines_to_use)
        inf_lines_to_use, true_lines_to_use = get_tree_metric_lines(annotations, cpath, reco_info, use_true_clusters, only_use_best_partition=only_use_best_partition, glfo=glfo)  # NOTE these continue to be modified (by removing clusters we don't want) further down, and then they get passed to the plotting functions

    # get tree and calculate metrics for inferred lines
    if inf_lines_to_use is not None and true_lines_to_use is None:  # if we have true lines, we don't run anything on inferred lines (at least atm)
        n_before = len(inf_lines_to_use)
        inf_lines_to_use = sorted([l for l in inf_lines_to_use if len(l['unique_ids']) >= min_cluster_size], key=lambda l: len(l['unique_ids']), reverse=True)
        n_after = len(inf_lines_to_use)  # after removing the small ones
        treefos = None
        if 'tree' in args.selection_metric_plot_cfg or any(m in metrics_to_calc for m in ['lbi', 'lbr', 'lbf', 'aa-lbi', 'aa-lbr', 'aa-lbf']):  # get the tree if we're making tree plots or if any of the requested metrics need a tree
            treefos = get_trees_for_annotations(inf_lines_to_use, treefname=treefname, cpath=cpath, workdir=workdir, cluster_indices=args.cluster_indices, run_gctree=args.run_gctree, gctree_outdir=gctree_outdir, glfo=glfo, debug=debug)
        print '    calculating selection metrics for %d cluster%s with size%s: %s' % (n_after, utils.plural(n_after), utils.plural(n_after), ' '.join(str(len(l['unique_ids'])) for l in inf_lines_to_use))
        print '      skipping %d smaller than %d' % (n_before - n_after, min_cluster_size)
        check_cluster_indices(args.cluster_indices, n_after, inf_lines_to_use)
        n_already_there, n_skipped_uid = 0, 0
        final_inf_lines = []
        for iclust, line in enumerate(inf_lines_to_use):
            if args.cluster_indices is not None and iclust not in args.cluster_indices:
                continue
            if debug:
                print '  %s sequence cluster' % utils.color('green', str(len(line['unique_ids'])))

            if 'tree-info' in line:  # NOTE we used to continue here, but now I've decided we really want to overwrite what's there (although I'm a little worried that there was a reason I'm forgetting not to overwrite them)
                if debug:
                    print '       %s overwriting selection metric info that was already in <line>' % utils.color('yellow', 'warning')
                n_already_there += 1
            if 'tree-info' not in line:
                line['tree-info'] = {'lb' : {}}
            if treefos is not None:
                trfo = treefos[iclust]
                if trfo['tree'] is not None:
                    line['tree-info']['lb']['tree'] = trfo['tree'].as_string(schema='newick')
            if 'cons-dist-aa' in metrics_to_calc:
                add_cdists_to_lbfo(line, line['tree-info']['lb'], 'cons-dist-aa', debug=debug)  # this adds the values both directly to the <line>, and to <line['tree-info']['lb']>, but the former won't end up in the output file unless the corresponding keys are specified as extra annotation columns (this distinction/duplication is worth having, although it's not ideal)

            if any(m in metrics_to_calc for m in ['lbi', 'lbr', 'lbf', 'aa-lbi', 'aa-lbr', 'aa-lbf']):
                if trfo['tree'] is None and trfo['origin'] == 'no-uids':
                    n_skipped_uid += 1
                    continue
                if any(m in metrics_to_calc for m in ['lbi', 'lbr', 'lbf']):
                    lbfo = calculate_lb_values(trfo['tree'], lb_tau, annotation=line, dont_normalize=args.dont_normalize_lbi, extra_str='inf tree', iclust=iclust, debug=debug)
                    check_lb_values(line, lbfo)  # would be nice to remove this eventually, but I keep runnining into instances where dendropy is silently removing nodes
                    line['tree-info']['lb'].update(lbfo)
                if any(m in metrics_to_calc for m in ['aa-lbi', 'aa-lbr', 'aa-lbf']):
                    get_aa_lb_metrics(line, trfo['tree'], lb_tau, dont_normalize_lbi=args.dont_normalize_lbi, extra_str='(AA inf tree, iclust %d)'%iclust, iclust=iclust, debug=debug)

            if args.dtr_path is not None and not train_dtr:  # don't want to train on data (NOTE this would probably also need all the lb metrics calculated, but i don't care atm)
                calc_dtr(False, line, line['tree-info']['lb'], trfo['tree'], None, pmml_models, dtr_cfgvals)  # adds predicted dtr values to lbfo (hardcoded False and None are to make sure we don't train on data)

            for mtmp in [m for m in metrics_to_calc if m not in line['tree-info']['lb']]:  # ick (but we want it to work for e.g. the metric 'shm' which isn't the name of the annotation key)
                line['tree-info']['lb'][mtmp] = {u : utils.antnval(line, mtmp, i) for i, u in enumerate(line['unique_ids'])}

            final_inf_lines.append(line)

        if n_skipped_uid > 0:
            print '    skipped %d/%d clusters that had no uids in common with tree in %s' % (n_skipped_uid, n_after, treefname)
        if n_already_there > 0:
            print '    %s replaced tree info in %d / %d that already had it' % (utils.color('yellow', 'warning'), n_already_there, n_after)

        inf_lines_to_use = final_inf_lines  # replace it with a new list that only has the clusters we really want

    # calculate lb values for true lines/trees
    if true_lines_to_use is not None:  # note that if <base_plotdir> *isn't* set, we don't actually do anything with the true lb values
        n_true_before = len(true_lines_to_use)
        true_lines_to_use = sorted([l for l in true_lines_to_use if len(l['unique_ids']) >= min_cluster_size], key=lambda l: len(l['unique_ids']), reverse=True)
        n_true_after = len(true_lines_to_use)
        print '    also doing %d true cluster%s with size%s: %s' % (n_true_after, utils.plural(n_true_after), utils.plural(n_true_after), ' '.join(str(len(l['unique_ids'])) for l in true_lines_to_use))
        print '      skipping %d smaller than %d' % (n_true_before - n_true_after, min_cluster_size)
        final_true_lines = []
        for iclust, true_line in enumerate(true_lines_to_use):
            if args.cluster_indices is not None and iclust not in args.cluster_indices:
                continue
            true_dtree = get_dendro_tree(treestr=true_line['tree'])
            true_lb_info = calculate_lb_values(true_dtree, lb_tau, annotation=true_line, dont_normalize=args.dont_normalize_lbi, extra_str='true tree', iclust=iclust, debug=debug)
            true_line['tree-info'] = {'lb' : true_lb_info}
            check_lb_values(true_line, true_line['tree-info']['lb'])  # would be nice to remove this eventually, but I keep runnining into instances where dendropy is silently removing nodes
            if any(m in metrics_to_calc for m in ['aa-lbi', 'aa-lbr']):
                get_aa_lb_metrics(true_line, true_dtree, lb_tau, dont_normalize_lbi=args.dont_normalize_lbi, extra_str='(AA true tree, iclust %d)'%iclust, iclust=iclust, debug=debug)
            if 'cons-dist-aa' in metrics_to_calc:
                add_cdists_to_lbfo(true_line, true_line['tree-info']['lb'], 'cons-dist-aa', debug=debug)  # see comment in previous call above
            if args.dtr_path is not None:
                calc_dtr(train_dtr, true_line, true_lb_info, true_dtree, trainfo, pmml_models, dtr_cfgvals)  # either adds training values to trainfo, or adds predicted dtr values to lbfo
            for mtmp in [m for m in metrics_to_calc if m not in true_line['tree-info']['lb']]:  # ick (but we want it to work for e.g. the metric 'shm' which isn't the name of the annotation key)
                true_line['tree-info']['lb'][mtmp] = {u : utils.antnval(true_line, mtmp, i) for i, u in enumerate(true_line['unique_ids'])}
            final_true_lines.append(true_line)
        true_lines_to_use = final_true_lines  # replace it with a new list that only has the clusters we really want

    if true_lines_to_use is None:  # don't plot inferred metrics on simulation (saves time + complication, and we hardly ever actually want them)
        plstr, antn_list, is_simu, inf_annotations = 'inferred', inf_lines_to_use, False, None
    else:
        plstr, antn_list, is_simu, inf_annotations = 'true', true_lines_to_use, True, inf_lines_to_use
    if args.dtr_path is not None:  # it would be nice to eventually merge these two blocks, i.e. use the same code to plot dtr and lbi/lbr
        if train_dtr:
            print '  training decision trees into %s' % args.dtr_path
            if dtr_cfgvals['n_train_per_family'] is not None:
                print '     n_train_per_family: using only %d from each family for among-families dtr' % dtr_cfgvals['n_train_per_family']
            for cg in cgroups:
                for tvar in dtr_targets[cg]:
                    train_dtr_model(trainfo[cg][tvar], args.dtr_path, dtr_cfgvals, cg, tvar)
        elif base_plotdir is not None:
            assert true_lines_to_use is not None
            plstart = time.time()
            assert ete_path is None or workdir is not None  # need the workdir to make the ete trees
            import plotting
            import lbplotting
            # if 'affinities' not in annotations[0] or all(affy is None for affy in annotations[0]['affinities']):  # if it's bcr-phylo simulation we should have affinities for everybody, otherwise for nobody
            #     return
            print '           plotting to %s' % base_plotdir
            true_plotdir = base_plotdir + '/true-tree-metrics'
            lbmlist = sorted(m for m in dtr_metrics if m not in missing_models)  # sorted() is just so the order in the html file matches that in the lb metric one
            utils.prep_dir(true_plotdir, wildlings=['*.svg', '*.html'], allow_other_files=True, subdirs=lbmlist)
            fnames = []
            for lbm in lbmlist:
                if 'delta-affinity' in lbm:
                    lbplotting.plot_lb_vs_ancestral_delta_affinity(true_plotdir+'/'+lbm, true_lines_to_use, lbm, is_true_line=True, only_csv=args.only_csv_plots, fnames=fnames, debug=debug)
                else:
                    for affy_key in (['affinities', 'relative_affinities'] if args.include_relative_affy_plots else ['affinities']):
                        lbplotting.plot_lb_vs_affinity(true_plotdir, true_lines_to_use, lbm, is_true_line=True, only_csv=args.only_csv_plots, fnames=fnames, affy_key=affy_key)
            if not args.only_csv_plots:
                plotting.make_html(true_plotdir, fnames=fnames, extra_links=[(subd, '%s/%s/' % (true_plotdir, subd)) for subd in lbmlist])
            print '      dtr plotting time %.1fs' % (time.time() - plstart)
    elif base_plotdir is not None:
        assert ete_path is None or workdir is not None  # need the workdir to make the ete trees
        plot_tree_metrics(args, '%s/%s-tree-metrics' % (base_plotdir, plstr), metrics_to_calc, antn_list, is_simu=is_simu, inf_annotations=inf_annotations, ete_path=ete_path, workdir=workdir, debug=debug)

    if outfname is not None:
        print '  writing selection metrics to %s' % outfname
        utils.prep_dir(None, fname=outfname, allow_other_files=True)
        def dumpfo(tl):
            dumpfo = {'unique_ids' : l['unique_ids']}
            dumpfo.update(l['tree-info'])
            return dumpfo
        with open(outfname, 'w') as tfile:
            json.dump([dumpfo(l) for l in antn_list if 'tree-info' in l], tfile)
    if args.run_gctree and gctree_outdir is not None:
        anfname = '%s/gctree-annotations.yaml' % gctree_outdir
        print '    writing gctree annotations (with inferred ancestral sequences) to %s' % anfname
        utils.write_annotations(anfname, glfo, antn_list, utils.add_lists(list(utils.annotation_headers), args.extra_annotation_columns))  # NOTE these probably have the fwk insertions removed, which is probably ok?

# ----------------------------------------------------------------------------------------
def init_dtr(train_dtr, dtr_path, cfg_fname=None):
    # ----------------------------------------------------------------------------------------
    def read_cfg():
        if cfg_fname is None:  # just use the defaults
            dtr_cfgvals = {}
        else:  # read cfg values from a file
            with open(cfg_fname) as yfile:
                dtr_cfgvals = yaml.load(yfile, Loader=Loader)
            if 'vars' in dtr_cfgvals:  # format is slightly different in the file (in the file we don't require the explicit split between per-seq and per-cluster variables)
                allowed_vars = set(v for cg in cgroups for pc in dtr_vars[cg] for v in dtr_vars[cg][pc])
                cfg_vars = set(v for cg in cgroups for v in dtr_cfgvals['vars'][cg])
                bad_vars = cfg_vars - allowed_vars
                if len(bad_vars) > 0:
                    raise Exception('unexpected dtr var%s (%s) in cfg file %s' % (utils.plural(len(bad_vars)), ', '.join(bad_vars), cfg_fname))
                for cg in cgroups:
                    dtr_cfgvals['vars'][cg] = {pc : [v for v in dtr_vars[cg][pc] if v in dtr_cfgvals['vars'][cg]] for pc in pchoices}  # loop over the allowed vars here so the order is always the same
        for tk in set(default_dtr_options) - set(dtr_cfgvals):  # set any missing ones to the defaults
            if tk == 'vars':
                dtr_cfgvals[tk] = dtr_vars
            elif tk == 'n_jobs':
                dtr_cfgvals[tk] = utils.auto_n_procs()  # isn't working when I put it up top, not sure why
            else:
                dtr_cfgvals[tk] = default_dtr_options[tk]
        return dtr_cfgvals
    # ----------------------------------------------------------------------------------------
    def read_model(cg, tvar):
        if 'pypmml' not in sys.modules:
            import pypmml
        picklefname, pmmlfname = dtrfname(dtr_path, cg, tvar), dtrfname(dtr_path, cg, tvar, suffix='pmml')
        if os.path.exists(picklefname):  # pickle file (i.e. with entire model class written to disk, but *must* be read with the same version of sklearn that was used to write it) [these should always be there, since on old ones they were all we had, and on new ones we write both pickle and pmml]
            if os.path.exists(pmmlfname):  # pmml file (i.e. just with the info to make predictions, but can be read with other software versions)
                pmml_models[cg][tvar] = sys.modules['pypmml'].Model.fromFile(pmmlfname)
            else:  # if the pmml file isn't there, this must be old files, so we read the pickle, convert to pmml, then read that new pmml file
                if 'joblib' not in sys.modules:  # just so people don't need to install it unless they're training (also scons seems to break it https://stackoverflow.com/questions/24453387/scons-attributeerror-builtin-function-or-method-object-has-no-attribute-disp)
                    import joblib
                with open(picklefname) as dfile:
                    skmodels[cg][tvar] = sys.modules['joblib'].load(dfile)
                write_pmml(pmmlfname, skmodels[cg][tvar], get_dtr_varnames(cg, dtr_cfgvals['vars']), tvar)
                pmml_models[cg][tvar] = sys.modules['pypmml'].Model.fromFile(pmmlfname)
        else:
            if cg == 'among-families' and tvar == 'delta-affinity':  # this is the only one that should be missing, since we added it last
                missing_models.append('-'.join([cg, tvar, metric_method]))  # this is fucking dumb, but I need it later when I have the full name, not cg and tvar
                print ' %s %s doesn\'t exist, skipping (%s)' % (cg, tvar, dtrfname(dtr_path, cg, tvar))
                return
            raise Exception('model file doesn\'t exist: %s' % picklefname)

    # ----------------------------------------------------------------------------------------
    dtr_cfgvals = read_cfg()

    skmodels = {cg : {tv : None for tv in dtr_targets[cg]} for cg in cgroups}
    pmml_models = {cg : {tv : None for tv in dtr_targets[cg]} for cg in cgroups}
    missing_models = []
    trainfo = None
    if train_dtr:
        trainfo = {cg : {tv : {'in' : [], 'out' : []} for tv in dtr_targets[cg]} for cg in cgroups}  # , 'weights' : []}
    else:
        rstart = time.time()
        for cg in cgroups:
            for tvar in dtr_targets[cg]:
                read_model(cg, tvar)
        print '  read decision trees from %s (%.1fs)' % (dtr_path, time.time() - rstart)

    return dtr_cfgvals, trainfo, skmodels, pmml_models, missing_models

# ----------------------------------------------------------------------------------------
def calc_dtr(train_dtr, line, lbfo, dtree, trainfo, pmml_models, dtr_cfgvals, skmodels=None):  # either add training values for <line>, or predict on it
    # ----------------------------------------------------------------------------------------
    def add_dtr_training_vals(cg, tvar, dtr_invals):  # transfer dtr input values to tfo['in'], and add output (affinity stuff) values to tfo['out']
        # trainfo[XXX]['weights'] += line['affinities']
        def get_delta_affinity_vals():
            tmpvals = {s : [] for s in tfo}
            for iseq, uid in enumerate(line['unique_ids']):
                if iseq==0:
                    print '%s dtr training target should be updated to include get_n_descendents_to_affy_increase()' % utils.color('yellow', 'warning')
                n_steps = get_n_ancestors_to_affy_change(None, dtree.find_node_with_taxon_label(uid), dtree, line)
                if n_steps is None:  # can't train on None-type values
                    continue
                tmpvals['in'].append(dtr_invals[cg][iseq])
                tmpvals['out'].append(-n_steps)
            return tmpvals
        tfo = trainfo[cg][tvar]
        if cg == 'within-families':
            if tvar == 'affinity':
                tfo['in'] += dtr_invals[cg]
                max_affy = max(line['affinities'])
                tfo['out'] += [a / max_affy for a in line['affinities']]
            elif tvar == 'delta-affinity':
                tmpvals = get_delta_affinity_vals()
                tfo['in'] += tmpvals['in']
                tfo['out'] += tmpvals['out']
            else:
                assert False
        elif cg == 'among-families':
            if dtr_cfgvals['n_train_per_family'] is None:
                assert tvar == 'affinity'  # eh why bother doing the other one
                tfo['in'] += dtr_invals[cg]
                tfo['out'] += line['affinities']
            else:
                if tvar == 'affinity':
                    i_to_keep = numpy.random.choice(range(len(line['unique_ids'])), size=dtr_cfgvals['n_train_per_family'], replace=False)
                    tfo['in'] += [dtr_invals[cg][i] for i in i_to_keep]
                    tfo['out'] += [line['affinities'][i] for i in i_to_keep]
                elif tvar == 'delta-affinity':
                    tmpvals = get_delta_affinity_vals()
                    if len(tmpvals['in']) == 0:  # no affinity increases
                        return
                    i_to_keep = numpy.random.choice(range(len(tmpvals['in'])), size=dtr_cfgvals['n_train_per_family'], replace=False)
                    tfo['in'] += [tmpvals['in'][i] for i in i_to_keep]
                    tfo['out'] += [tmpvals['out'][i] for i in i_to_keep]
                else:
                    assert False
        else:
            assert False

    # ----------------------------------------------------------------------------------------
    utils.add_naive_seq_aa(line)
    utils.add_seqs_aa(line)
    for mtmp in ['cons-dist-nuc', 'cons-dist-aa']:
        add_cdists_to_lbfo(line, lbfo, mtmp)

    dtr_invals = {cg : get_dtr_vals(cg, dtr_cfgvals['vars'], line, lbfo, dtree) for cg in cgroups}  # all dtr input variable values, before we fiddle with them for the different dtrs
    if train_dtr:  # train and write new model
        for cg in cgroups:
            for tvar in dtr_targets[cg]:
                add_dtr_training_vals(cg, tvar, dtr_invals)
    else:  # read existing model
        for cg in cgroups:
            for tvar in dtr_targets[cg]:
                if pmml_models[cg][tvar] is None:  # only way this can happen atm is old dirs that don't have among-families delta-affinity
                    continue
                outfo = {}
                for iseq, uid in enumerate(line['unique_ids']):
                    pmml_invals = {var : val for var, val in zip(get_dtr_varnames(cg, dtr_cfgvals['vars']), dtr_invals[cg][iseq])}  # convert from format for sklearn to format for pmml
                    outfo[uid] = pmml_models[cg][tvar].predict(pmml_invals)['predicted_%s'%tvar]
                    # if skmodels[cg][tvar] is not None:  # leaving this here cause maybe we'll want to fall back to it or something if pmml ends up having problems
                    #     sk_val = skmodels[cg][tvar].predict([dtr_invals[cg][iseq]])
                    #     assert utils.is_normed(sk_val / outfo[uid])
                lbfo['-'.join([cg, tvar, 'dtr'])] = outfo  # NOTE it would be nice to automate this '-'.join() conversion, it happens in a few places already

# ----------------------------------------------------------------------------------------
# differences to add_smetrics(): this fcn
#    1) can run a bunch of metrics that the other can't
#    2) mosty focuses on running one metric at a time (as opposed to running all the ones that we typically want on data)
#    3) doesn't plot as many things
#    4) only runs on simulation (as opposed to making two sets of things, for simulation and data)
# and yes, it would be really *#(!$ing nice to merge them but I haven't had the time yet
def calculate_individual_tree_metrics(metric_method, annotations, base_plotdir=None, ete_path=None, workdir=None, lb_tau=None, only_csv=False, min_cluster_size=None, include_relative_affy_plots=False,
                                      dont_normalize_lbi=False, cluster_indices=None, only_look_upwards=False, args=None, debug=False):
    # ----------------------------------------------------------------------------------------
    def get_combo_lbfo(varlist, iclust, line, lb_tau, is_aa_lb=False): #, add_to_line=False):
        if 'shm-aa' in varlist and 'seqs_aa' not in line:
            utils.add_naive_seq_aa(line)
            utils.add_seqs_aa(line)
        lbfo = {}
        for mtmp in [m for m in varlist if 'cons-dist-' in m]:
            add_cdists_to_lbfo(line, lbfo, mtmp)
        dtree = get_dendro_tree(treestr=line['tree'])
# TODO this doesn't really make sense, i'm using is_aa_lb to control what hould be in <varlist>
        if is_aa_lb:  # NOTE this adds the metrics to <line>
            get_aa_lb_metrics(line, dtree, lb_tau, dont_normalize_lbi=dont_normalize_lbi, extra_str='true tree', iclust=iclust, debug=debug)
            lbfo.update(line['tree-info']['lb'])
        else:
            lbvars = [m for m in varlist if m[:2]=='lb']  # don't really need this any more i thinkg
            tmp_lb_info = calculate_lb_values(dtree, lb_tau, metrics_to_calc=lbvars, annotation=line, dont_normalize=dont_normalize_lbi, extra_str='true tree', iclust=iclust, debug=debug)
            for lbm in [m for m in lb_metrics if m in varlist]:  # this skips the tree, which I guess isn't a big deal
                lbfo[lbm] = {u : tmp_lb_info[lbm][u] for u in line['unique_ids']}  # remove the ones that aren't in <line> (since we don't have sequences for them, so also no consensus distance)
        # if add_to_line:
        #     line['tree-info'] = {'lb' : lbfo}
        return dtree, lbfo

    # ----------------------------------------------------------------------------------------
    def add_to_treefo(lbfo):
        if 'tree-info' in line:
            wstr = (' %s replacing existing info'%utils.wrnstr()) if metric_method in line['tree-info']['lb'] else ''
            if debug: print '    add %s to existing lb keys:  %s%s' % (metric_method, ' '.join(k for k in line['tree-info']['lb']), wstr)
            line['tree-info']['lb'][metric_method] = lbfo
        else:
            if debug: print '    add new metric %s' % metric_method
            line['tree-info'] = {'lb' : {metric_method : lbfo}}
    # ----------------------------------------------------------------------------------------
    if min_cluster_size is None:
        min_cluster_size = default_min_selection_metric_cluster_size
    n_before = len(annotations)
    annotations = sorted([l for l in annotations if len(l['unique_ids']) >= min_cluster_size], key=lambda l: len(l['unique_ids']), reverse=True)
    n_after = len(annotations)
    print '      %s getting individual metric for %d true cluster%s with size%s: %s' % (utils.color('blue', metric_method), n_after, utils.plural(n_after), utils.plural(n_after), ' '.join(str(len(l['unique_ids'])) for l in annotations))
    if n_before - n_after > 0:
        print '        skipping %d smaller than %d' % (n_before - n_after, min_cluster_size)

    pstart = time.time()
    metric_antns = []  # just to keep track of the ones corresponding to <cluster_indices> (if set)
    for iclust, line in enumerate(annotations):
        if cluster_indices is not None and iclust not in cluster_indices:
            continue
        metric_antns.append(line)
        if 'tree-info' in line and 'lb' in line['tree-info'] and metric_method in line['tree-info']['lb']:
            print '    %s already in annotation, not doing anything' % metric_method
            continue
        if metric_method in ['shm', 'shm-aa']:
            metric_info = {u : utils.antnval(line, metric_method, i) for i, u in enumerate(line['unique_ids'])}
            add_to_treefo(metric_info)
        elif metric_method == 'fay-wu-h':  # NOTE this isn't actually tree info, but I"m comparing it to things calculated with a tree, so putting it in the same place at least for now
            fwh = -utils.fay_wu_h(line)
            add_to_treefo({u : fwh for i, u in enumerate(line['unique_ids'])}) # kind of weird to set it individually for each sequence when they all have the same value (i.e. it's a per-family metric), but I don't want to do actual per-family comparisons any more, and this way we can at least look at it
        elif metric_method in ['cons-dist-nuc', 'cons-dist-aa']:
            lbfo = {}
            add_cdists_to_lbfo(line, lbfo, metric_method)
            add_to_treefo(lbfo[metric_method])
        elif metric_method == 'delta-lbi':
            dtree, lbfo = get_combo_lbfo(['lbi'], iclust, line, lb_tau)
            delta_lbfo = {}
            for uid in line['unique_ids']:
                node = dtree.find_node_with_taxon_label(uid)
                if node is dtree.seed_node:
                    continue  # maybe I should add it as something? not sure
                delta_lbfo[uid] = lbfo['lbi'][uid] - lbfo['lbi'][node.parent_node.taxon.label]  # I think the parent should always be in here, since I think we should calculate lbi for every node in the tree
            add_to_treefo(delta_lbfo)
        elif 'aa-lb' in metric_method:  # aa versions of lbi and lbr
            _, lbfo = get_combo_lbfo([metric_method.lstrip('aa-')], iclust, line, lb_tau, is_aa_lb=True)  # NOTE i shouldn't have used lstrip() here (i keep forgetting it's character-based, not string-based', but i think it's ok
            # NOTE do *not* call add_to_treefo() since they're already added to <line>
        elif metric_method in ['lbi', 'lbr', 'lbf']:
            _, lbfo = get_combo_lbfo([metric_method], iclust, line, lb_tau) #, add_to_line=True)
            add_to_treefo(lbfo[metric_method])
        elif metric_method == 'cons-lbi':
            cmetrics = ['cons-dist-aa', 'aa-lbi']
            _, lbfo = get_combo_lbfo(cmetrics, iclust, line, lb_tau, is_aa_lb=True)
            mbounds = {}
            for mtr in cmetrics:
                mbounds[mtr] = [mfn(lbfo[mtr].values()) for mfn in (min, max)]
            def zscore(mtr, uid):
                return (lbfo[mtr][uid] - mbounds[mtr][0]) / float(mbounds[mtr][1] - mbounds[mtr][0])
            def mcombine(uid):
                return numpy.prod([zscore(m, uid) for m in cmetrics])
            combovals = {u : mcombine(u) for u in line['unique_ids']}
            # for u, v in sorted(combovals.items(), key=operator.itemgetter(1)):
            #     print '  %.3f  %.5f   %3.0f  %.5f   %.7f %s' % (lbfo['aa-lbi'][u], zscore('aa-lbi', u), lbfo['cons-dist-aa'][u], zscore('cons-dist-aa', u), v, u)
            add_to_treefo(combovals)
        else:
            assert False

    if time.time() - pstart > 60:
        print '       tree quantity calculation/prediction time: %.1fs' % (time.time() - pstart)

    if base_plotdir is not None:
        assert ete_path is None or workdir is not None  # need the workdir to make the ete trees
        plstr, is_simu, inf_annotations = 'true', True, None
        plot_tree_metrics(args, '%s/%s-tree-metrics' % (base_plotdir, plstr), [metric_method], metric_antns, is_simu=is_simu, inf_annotations=inf_annotations, ete_path=ete_path, workdir=workdir, debug=debug)

# ----------------------------------------------------------------------------------------
def run_laplacian_spectra(treestr, workdir=None, plotdir=None, plotname=None, title=None, debug=False):
    #  - https://www.ncbi.nlm.nih.gov/pubmed/26658901/
    #  - instructions here: https://besjournals.onlinelibrary.wiley.com/doi/full/10.1111/2041-210X.12526
    # I think this is what ended up working (thought probably not in docker):
    #  apt-get install libgmp-dev libmpfr-dev
    #  > install.packages("RPANDA",dependencies=TRUE)
    #  ok but then I needed to modify the code, so downloaded the source from cran, and swapped out for the spectR.R that eric sent, then installed with:
    # R CMD INSTALL -l packages/RPANDA/lib packages/RPANDA/  # NOTE needs to happen whenever you modify the R source
    # condensation of docs from the above paper:
    #  - > res<-spectR(Phyllostomidae)  # compute eigenvalues (and some metrics describing the distribution, e.g. skewness, kurtosis, eigengap)
    #  - > plot_spectR(res)  # make plots for eigenvalue spectrum
    #  - if eigengap (largest gap between sorted eigenvalues) is e.g. between 3 and 4, then the tree can be separated into three regions, and you use the BIC stuff to find those regions
    #    - > res<-BICompare(Phyllostomidae,3)
    #    - > plot_BICompare(Phyllostomidae,res)
    #  - > res<-JSDtree(Phyllostomidae_genera)  # pairwise jensen-shannon distances between the 25 phylogenies
    #  - > JSDtree_cluster(res)  # plots heatmap and hierarchical cluster

    if debug:
        print utils.pad_lines(get_ascii_tree(treestr=treestr))
        print treestr

    if workdir is None:
        workdir = utils.choose_random_subdir('/tmp/%s' % os.getenv('USER', default='partis-work'))
    eigenfname = '%s/eigenvalues.txt' % workdir
    os.makedirs(workdir)

    cmdlines = [
        'library(ape, quiet=TRUE)',
        # 'library(RPANDA, quiet=TRUE)',  # old way, before I had to modify the source code because the CRAN version removes all eigenvalues <1 (for method="standard" -- with method="normal" it's <0, which is probably better, but it also seems to smoosh all the eigenvalues to be almost exactly 1)
        'library("RPANDA", lib.loc="%s/packages/RPANDA/lib", quiet=TRUE)' % os.path.dirname(os.path.realpath(__file__)).replace('/python', ''),
        'tree <- read.tree(text = "%s")' % treestr,
        # 'print(tree)',
        'specvals <- spectR(tree, method=c("standard"))',  # compute eigenvalues (and some metrics describing the distribution, e.g. skewness, kurtosis, eigengap)
        # 'print(specvals)',
        'capture.output(specvals$eigenvalues, file="%s")' % eigenfname,
    ]

    outstr, errstr = utils.run_r(cmdlines, workdir, return_out_err=True)  # if it crashes, call it without return_out_err, so it prints stuff as it goes
    errstr = '\n'.join([l.strip() for l in errstr.split('\n') if 'This is vegan' not in l])
    for oestr in (outstr, errstr):
        if oestr.strip() == '':
            continue
        print utils.pad_lines(outstr)

    eigenvalues = []
    with open(eigenfname) as efile:
        for line in efile:
            for tstr in line.split():
                if '[' in tstr:
                    if int(tstr.strip('[]')) != len(eigenvalues) + 1:
                        raise Exception('couldn\'t process line:\n%s' % line)
                else:
                    eigenvalues.append(float(tstr))

    os.remove(eigenfname)
    os.rmdir(workdir)

    if plotdir is not None:
        import plotting
        plotting.plot_laplacian_spectra(plotdir, plotname, eigenvalues, title)

# ----------------------------------------------------------------------------------------
def combine_selection_metrics(lp_infos, min_cluster_size=default_min_selection_metric_cluster_size, plotdir=None, ig_or_tr='ig', args=None, is_simu=False):  # don't really like passing <args> like this, but it's the easiest cfg convention atm
    # ----------------------------------------------------------------------------------------
    def gsval(mfo, tch, vname, no_fail=False):
        cln, iseq = mfo[tch], mfo[tch+'_iseq']
        return utils.antnval(cln, vname, iseq, use_default=no_fail)
    # ----------------------------------------------------------------------------------------
    def p_gsval(mfo, vname, no_fail=False):
        cln, iseq = mfo['p_atn'], mfo['p_atn']['unique_ids'].index(combid(mfo))
        return utils.antnval(cln, vname, iseq, use_default=no_fail)
    # ----------------------------------------------------------------------------------------
    def gsvstr(val, vname):
        if val is None:
            return '?' #str(val)
        if vname in args.selection_metrics_to_calculate:
            return '%.2f' % val
        elif vname == 'affinities':
            return ('%.1f' % val) if val > 1 else str(utils.round_to_n_digits(val, 2))  # could probably round for the first case as well
        elif type(val) == float:
            return '%.3f' % val
        else:
            return str(val)
    # ----------------------------------------------------------------------------------------
    def sumv(mfo, kstr):
        if kstr == 'seq_mtps':  # NOTE this is the sum of utils.get_multiplicity() over identical sequences
            def vfcn(c): return mtpys[c][gsval(mfo, c, 'input_seqs_aa')]
        else:
            def vfcn(c): return gsval(mfo, c, kstr)
        kvals = [vfcn(c) for c in 'hl']
        return None if None in kvals else kvals[0] + kvals[1]  # needs to work for both ints and strings
    # ----------------------------------------------------------------------------------------
    def sum_nuc_shm_pct(mpfo):
        total_len = sum(len(gsval(mpfo, c, 'seqs')) - gsval(mpfo, c, 'seqs').count(utils.ambig_base) for c in 'hl')
        return 100 * sumv(mpfo, 'n_mutations') / float(total_len)
    # ----------------------------------------------------------------------------------------
    def get_did(uid, return_contigs=False):
        return utils.get_droplet_id(uid, args.droplet_id_separators, args.droplet_id_indices, return_contigs=return_contigs)
    # ----------------------------------------------------------------------------------------
    def both_dids(mfo):
        return [get_did(gsval(mfo, c, 'unique_ids')) for c in 'hl']
    # ----------------------------------------------------------------------------------------
    def get_joint_did(mfo):
        return utils.get_single_entry(list(set(both_dids(mfo))))
    # ----------------------------------------------------------------------------------------
    def combid(mfo):  # new uid that combines h+l ids
        _, cids = zip(*[get_did(gsval(mfo, c, 'unique_ids'), return_contigs=True) for c in 'hl'])
        dids = both_dids(mfo)  # the vast majority of the time they have the same did, so this is just the did, but in simulation, if they're mispaired, they can be different
        if len(set(dids)) == 1:  # if they have the same droplet id (data or correctly paired simulation)
            if is_simu:  # in simulation the droplet ids should be unique, sowe can just use the droplet id as the combined id
                return dids[0]
            else:  # but in data we can get multiple cells per droplet id
                return '%s_contig_%s+%s' % (dids[0], cids[0], cids[1])
        else:  # but if they're mispaired in simulation (i.e. have different "droplet ids") then keep all the info
            assert len(set(dids)) == 2
            return '%s-%s+%s-%s' % (dids[0], lpair[0], dids[1], lpair[1])
    # ----------------------------------------------------------------------------------------
    def get_didstr(dids, cids, mpfo):
        if len(set(dids)) == 1:  # make sure they're from the same droplet
            didstr = dids[0]
            if any('chosens' in mpfo[c] and gsval(mpfo, c, 'chosens') for c in 'hl'):
                didstr = utils.color('blue_bkg', didstr, width=20)
            if args.queries_to_include is not None and any(u in args.queries_to_include for u in (hid, lid)):
                didstr = utils.color('red', didstr, width=20)
        else:
            print '  %s paired seqs %s %s have different droplet ids (i.e. they were probably mis-paired) %s' % (utils.color('red', 'error'), hid, lid, dids)
            didstr = 'see error'
        cids = ['-' if c in utils.loci else c for c in cids]  # previously chosen unobserved cons seqs just have e.g. igh as the contig id, which we don't want to look at in the output
        return didstr, cids
    # ----------------------------------------------------------------------------------------
    def read_cfgfo():
        def iconvert(tcfg, vname):
            imax = max(tcfg.keys() + [cfgfo.get('n-families', 0) - 1])
            def_val = False if tcfg.values()[0] is True else 0
            nvals = [tcfg.get(i, def_val) for i in range(imax+1)]
            # if 'n-families' in cfgfo and cfgfo['n-families'] != imax + 1:  # i tried setting n-families automatically, but in practice it just tends to break things if you make it guess
            #     print '  %s \'n-families\' not equal to imax + 1 for %s' % (utils.wrnstr(), vname)
            # cfgfo['n-families'] = max(imax + 1, cfgfo['n-families'])
            return nvals
        allowed_keys = set(['n-families', 'n-per-family', 'include-unobs-cons-seqs', 'include-unobs-naive-seqs', 'vars', 'cell-types', 'cell-type-key', 'max-ambig-positions', 'min-umis', 'min-median-nuc-shm-%', 'min-hdist-to-already-chosen', 'droplet-ids', 'similar-to-droplet-ids', 'meta-info-print-keys', 'include_previously_chosen'])
        if debug:
            print '  ab choice cfg:'
            outstr, _ = utils.simplerun('cat %s'%args.ab_choice_cfg, return_out_err=True)
            print utils.pad_lines(outstr)
        with open(args.ab_choice_cfg) as cfile:
            cfgfo = yaml.load(cfile, Loader=Loader)
        if len(set(cfgfo) - allowed_keys) > 0:
            raise Exception('unexpected key[s] in ab choice cfg: %s (choose from: %s)' % (' '.join(set(cfgfo) - allowed_keys), ' '.join(allowed_keys)))
        for sortvar, vcfg in cfgfo['vars'].items():
            if vcfg['sort'] not in ['low', 'high']:
                raise Exception('value of sort var \'%s\' must be \'low\' or \'high\' (got \'%s\')' %(sortvar, vcfg['sort']))
            if 'i' in vcfg:
                vcfg['n'] = iconvert(vcfg['i'], sortvar)
            if 'n' in vcfg and len(vcfg['n']) != cfgfo['n-families']:
                raise Exception('length of n per family list %d for sort var %s doesn\'t match n-families %d' % (len(vcfg['n']), sortvar, cfgfo['n-families']))
        if 'n-per-family' in cfgfo and any('n' in vcfg for vcfg in cfgfo['vars'].values()):
            raise Exception('\'n-per-family\' was set, but also found key \'n\' in sort var[s] \'%s\' (can only specify number to take in one place)' % (' '.join(v for v, vcfg in cfgfo['vars'].items())))
        for stype in ['cons', 'naive']:
            tkey = 'include-unobs-%s-seqs'%stype
            if tkey not in cfgfo:
                cfgfo[tkey] = [False for _ in range(cfgfo['n-families'])]
            else:
                if hasattr(cfgfo[tkey], 'keys'):  # if it's a dict like {i: N}
                    cfgfo[tkey] = iconvert(cfgfo[tkey], tkey)
                if cfgfo[tkey] in [True, False]:  # if it's a single value, expand it to the right length
                    cfgfo[tkey] = [cfgfo[tkey] for _ in range(cfgfo['n-families'])]
                else:
                    if len(cfgfo[tkey]) != cfgfo['n-families']:
                        raise Exception('length of value for %s %d not equal to n-families %d' % (tkey, len(cfgfo[tkey]), cfgfo['n-families']))
                    if any(v not in [True, False] for v in cfgfo[tkey]):
                        raise Exception('values for %s must be bools but got: %s' % (tkey, ' '.join(str(v) for v in set(cfgfo[tkey]))))
        return cfgfo
    # ----------------------------------------------------------------------------------------
    def get_unobs_mfo(stype, metric_pairs, tdbg=False):
        assert stype in ['cons', 'naive']  # should be checked elsewhere, but not sure if it is
        # ----------------------------------------------------------------------------------------
        def use_iseqs(tch, mtmp, threshold=0.75):  # if any observed seqs in the family have shm indels, we need to figure out whether the indel should be included in the cons seq
            if stype == 'naive':  # inferred naive should never have indels in it
                return False
            hsil = mtmp[tch]['has_shm_indels']
            tstr = '(%d / %d = %.2f)' % (hsil.count(True), len(hsil), hsil.count(True) / float(len(hsil)))
            if hsil.count(True) / float(len(hsil)) > threshold:
                print '        %s more than %.2f %s of %s seqs have indels, so using *input* cons seq (note that if there\'s more than one indel, this may well be wrong, since you probably only want indels that are in a majority of the family [which is probably not all of them])' % (utils.color('yellow', 'warning'), threshold, tstr, tch)
                return True
            else:
                if any(hsil):  # if none of them have indels, don't print anything
                    print '        less than %.2f %s of %s seqs have indels, so not using input seqs for cons seq' % (threshold, tstr, tch)
                return False
        # ----------------------------------------------------------------------------------------
        def getcseqs(tch, use_input_seqs, aa=False, aa_ref_seq=None):
            if stype == 'cons':
                return utils.cons_seq_of_line(mtmp[tch], aa=aa, use_input_seqs=use_input_seqs, codon_len=1 if aa else 3, aa_ref_seq=aa_ref_seq)  # if we're not using input seqs and it's aa (so codon_len is 1) then it *should* be the same as the one that's already in the line
            else:
                return gsval(mtmp, tch, 'naive_seq'+('_aa' if aa else ''))
        # ----------------------------------------------------------------------------------------
        def tcsk(c, aastr):  # shortand for within this fcn
            return cskey(c, consfo, aastr=='aa')
        # ----------------------------------------------------------------------------------------
        mtmp = metric_pairs[0]
        uis = {c : use_iseqs(c, mtmp) for c in 'hl'}  # if any observed seqs in the family have shm indels, we need to figure out whether the indel should be included in the cons seq

        consfo = {c : mtmp[c] for c in 'hl'}
        consfo.update({'iclust' : iclust, 'seqtype' : stype})
        consfo.update({c+'_use_input_seqs' : uis[c] for c in 'hl'})
        consfo.update({tcsk(c, 'aa') : getcseqs(c, uis[c], aa=True) for c in 'hl'})
        consfo.update({tcsk(c, 'nuc') : getcseqs(c, uis[c], aa=False, aa_ref_seq=consfo[tcsk(c, 'aa')]) for c in 'hl'})

        if any(utils.ltranslate(consfo[tcsk(c, 'nuc')]) != consfo[tcsk(c, 'aa')] for c in 'hl'):
            print '  %s nuc %s seq translation differs from aa %s seq:' % (utils.color('yellow', 'warning'), stype, stype)
            print '              aa: %s %s' % tuple([consfo[tcsk(c, 'aa')] for c in 'hl'])
            print '      nuc trans.: %s %s' % tuple([utils.color_mutants(consfo[tcsk(c, 'aa')], utils.ltranslate(consfo[tcsk(c, 'nuc')]), amino_acid=True) for c in 'hl'])

        return consfo
    # ----------------------------------------------------------------------------------------
    def cskey(c, m, aa=False):
        assert m['seqtype'] != 'observed'
        return '%s_%sseq_%s' % (c, m['seqtype'][0], 'aa' if aa else 'nuc')
    # ----------------------------------------------------------------------------------------
    def ctkey():
        return cfgfo.get('cell-type-key', 'cell-types')  # allows multiple versions of cell type to be in annotation
    # ----------------------------------------------------------------------------------------
    def getseq(mfo, tch, aa=False):
        if mfo['seqtype'] == 'observed':
            return gsval(mfo, tch, 'input_seqs'+('_aa' if aa else ''))
        else:
            return mfo[cskey(tch, mfo, aa=aa)]
    # ----------------------------------------------------------------------------------------
    def nambig(mfo, tch, antn=None):
        if mfo['seqtype'] != 'observed':
            assert antn is not None  # need to pass in a real annotation if this is wasn't observed
        if antn is None:
            antn = mfo[tch]
        return utils.n_variable_ambig_aa(antn, getseq(mfo, tch, aa=True), getseq(mfo, tch, aa=False))
    # ----------------------------------------------------------------------------------------
    def mfseqs(mfo):
        return tuple(getseq(mfo, c, aa=True) for c in 'hl')
    # ----------------------------------------------------------------------------------------
    def in_chosen_seqs(all_chosen_seqs, mfo):  # NOTE all_chosen_seqs includes previously chosen ones
        return mfseqs(mfo) in all_chosen_seqs
    # ----------------------------------------------------------------------------------------
    def too_close_to_chosen_seqs(all_chosen_seqs, mfo, hdist, ttdbg=False):  # NOTE all_chosen_seqs includes previously chosen ones
        if len(all_chosen_seqs) == 0:
            return False
        if ttdbg:
            h_min, l_min = [min(local_hdist_aa(acseqs[i], mseq) for acseqs in all_chosen_seqs) for i, mseq in enumerate(mfseqs(mfo))]
            print '        %d %d %s' % (h_min, l_min, utils.color('red', 'x') if sum([h_min, l_min]) < hdist else '')
        return any(sum(local_hdist_aa(cseq, mseq) for mseq, cseq in zip(mfseqs(mfo), acseqs)) < hdist for acseqs in all_chosen_seqs)
    # ----------------------------------------------------------------------------------------
    def add_unobs_seq(stype, metric_pairs, chosen_mfos, all_chosen_seqs, tdbg=False):
        # get the consfo: first see if we observed the cons/naive seq (i.e. if there's any observed seqs with zero cdist)
        def kfcn(m): return sumv(m, 'aa-cfrac')==0 if stype=='cons' else sumv(m, 'n_mutations')==0  # NOTE cons is by aa, but naive is by nuc (since the naive nuc seq is actually really meaningful, and i don't want to have an additional kinda-sorta inferred naive seq floating around)
        obs_mfos = [m for m in metric_pairs if kfcn(m)]
        if 'max-ambig-positions' in cfgfo:
            obs_mfos = [m for m in obs_mfos if sum(nambig(m, c) for c in 'hl') <= cfgfo['max-ambig-positions']]
        if len(obs_mfos) > 0:  # if we observed the cons seq, use [one of] the observed ones
            obs_mfos = sorted(obs_mfos, key=lambda m: sumv(m, 'seq_mtps'), reverse=True)  # sort by mtpy
            consfo = obs_mfos[0]  # choose the first one
        else:  # if we didn't observe it (with some criteria),  make consfo from scratch
            print '            %s seq not observed' % stype
            consfo = get_unobs_mfo(stype, metric_pairs)
            n_ambig_bases = sum(nambig(consfo, c, antn=metric_pairs[0][c]) for c in 'hl')
            if 'max-ambig-positions' in cfgfo and n_ambig_bases > cfgfo['max-ambig-positions']:
                print '          %s seq: too many ambiguous bases in h+l (%d > %d)' % (stype, n_ambig_bases, cfgfo['max-ambig-positions'])
                return

        # apply some more criteria
        if in_chosen_seqs(all_chosen_seqs, consfo):
            print '          %s seq: seq identical to previously-chosen seq' % stype
            return
        if 'min-hdist-to-already-chosen' in cfgfo and too_close_to_chosen_seqs(all_chosen_seqs, consfo, cfgfo['min-hdist-to-already-chosen']):
            print '          %s seq: too close to previously-chosen seq' % stype
            return

        # add to chosen info
        chosen_mfos.append(consfo)
        all_chosen_seqs.add(tuple(getseq(consfo, c, aa=True) for c in 'hl'))
        if tdbg:
            indelstr = ''
            if any(consfo.get(c+'_use_input_seqs', False) for c in 'hl'):
                indelstr = ' (using %s input seq[s] becuase of indels)' % ' '.join(c for c in 'hl' if consfo[c+'_use_input_seqs'])
            zdstr = ''
            if len(obs_mfos) > 0:
                zdstr = ' (using observed seqs with aa-cdist zero %s)' % ' '.join(gsval(consfo, c, 'unique_ids') for c in 'hl')
            print '        %s: added %s seq%s%s' % (utils.color('green', 'x'), stype, indelstr, zdstr)
    # ----------------------------------------------------------------------------------------
    def local_hdist_aa(s1, s2, defval=None, frac=False):  # ick, this is ugly, but I think makes sense for now
        if len(s1) == len(s2):
            hfcn = utils.hamming_fraction if frac else utils.hamming_distance
            return hfcn(s1, s2, amino_acid=True)
        elif defval is not None:
            return defval
        else:
            return max([len(s1), len(s2)])  # NOTE it's kind of weird and arbitrary to return the max seq len if they're different lengths, but if they're different lengths we don't care anyway cause we're just looking for very similar sequences
    # ----------------------------------------------------------------------------------------
    def choose_abs(metric_pairs, iclust, tdbg=False):
        # ----------------------------------------------------------------------------------------
        def get_n_choose(tcfg, key):
            if key not in tcfg:
                return None
            if isinstance(tcfg[key], int):  # take the same number from each family
                return tcfg[key]
            else:  # specify a different number for each family
                if len(tcfg[key]) != cfgfo['n-families']:
                    raise Exception('length of n per family list for key %s (%d) not equal to n-families (%d)' % (key, len(tcfg[key]), cfgfo['n-families']))
                return tcfg[key][iclust]
        # ----------------------------------------------------------------------------------------
        def finished(tcfg=None, n_newly_chosen=None):
            if tcfg is not None:
                assert n_newly_chosen is not None
                # this takes the top <n> by <sortvar> (not including any unobs cons seq)
                if get_n_choose(tcfg, 'n') is not None and n_newly_chosen >= get_n_choose(tcfg, 'n'):  # number to choose for this var in this family
                    if debug:
                        print '        finished: %d newly chosen >= %d' % (n_newly_chosen, get_n_choose(tcfg, 'n'))
                    return True
            # whereas this makes sure we have N from the family over all sort vars (including any unobs cons seq), while still sorting by <sortvar>. It probably does *not* make sense to specify both versions
            is_finished = get_n_choose(cfgfo, 'n-per-family') is not None and len(chosen_mfos) >= get_n_choose(cfgfo, 'n-per-family')
            if debug and is_finished:
                print '        finished: %s' % ('n-per-family not specified' if get_n_choose(cfgfo, 'n-per-family') is None else '%d per family >= %d' % (len(chosen_mfos), get_n_choose(cfgfo, 'n-per-family')))
            return is_finished
        # ----------------------------------------------------------------------------------------
        def handle_droplet_sim_choice(refid, n_take, rmfo):
            def sfcn(m): return sum(utils.hamming_distance(gsval(m, c, 'seqs_aa'), gsval(rmfo, c, 'seqs_aa'), amino_acid=True) for c in 'hl')  # note: *not* input seqs, since they aren't in general all the same length
            if tdbg:
                altid = gsval(rmfo, 'h', 'alternate-uids', no_fail=True)
                print '      nearest to %s%s:' % (refid, ' (%s)'%altid if altid is not None else '')
                print '               hdist                          contig'
                print '             sum  h  l         droplet         h  l'
            n_chsn = 0
            for simfo in sorted(metric_pairs, key=sfcn):
                if n_chsn >= n_take:
                    break
                chsnstr = ' '
                if sfcn(simfo) > 0 and not in_chosen_seqs(all_chosen_seqs, simfo):
                    chosen_mfos.append(simfo)
                    all_chosen_seqs.add(tuple(gsval(simfo, c, 'input_seqs_aa') for c in 'hl'))
                    n_chsn += 1
                    chsnstr = utils.color('green', 'x')
                if tdbg:
                    dids, cids = zip(*[get_did(gsval(simfo, c, 'unique_ids'), return_contigs=True) for c in 'hl'])
                    didstr, cidstrs = get_didstr(dids, cids, simfo)
                    print '              %2d %2d %2d %s %20s  %s  %s  %s %s' % (sfcn(simfo),
                                                                                utils.hamming_distance(gsval(rmfo, 'h', 'seqs_aa'), gsval(simfo, 'h', 'seqs_aa'), amino_acid=True),
                                                                                utils.hamming_distance(gsval(rmfo, 'l', 'seqs_aa'), gsval(simfo, 'l', 'seqs_aa'), amino_acid=True),
                                                                                chsnstr, didstr, cidstrs[0], cidstrs[1],
                                                                                utils.color_mutants(gsval(rmfo, 'h', 'seqs_aa'), gsval(simfo, 'h', 'seqs_aa'), amino_acid=True),
                                                                                utils.color_mutants(gsval(rmfo, 'l', 'seqs_aa'), gsval(simfo, 'l', 'seqs_aa'), amino_acid=True)
                    )
            if tdbg:
                print '        chose %d abs similar to droplet id %s' % (n_chsn, refid)
        # ----------------------------------------------------------------------------------------
        # run through a bunch of options for skipping seqs/families
        if args.choose_all_abs:
            return metric_pairs
        if iclust >= cfgfo['n-families']:
            return []
        chosen_mfos = []  # includes unobs cons + naive seqs plus seqs chosen from all sortvars
        if finished():  # return if we weren't supposed to get any from this family
            return chosen_mfos
        if tdbg:
            print '    %s: choosing abs from joint cluster with size %d (marked with %s)' % (utils.color('green', 'iclust %d'%iclust), len(metric_pairs), utils.color('green', 'x'))

        all_chosen_seqs = set()  # just for keeping track of the seqs we've already chosen (note that this includes previously-chosen ones)

        if any('chosens' in mfo[c] for mfo in metric_pairs for c in 'hl'):  # add any previously-chosen seqs
            for mfo in metric_pairs:
                if any('chosens' in mfo[c] and gsval(mfo, c, 'chosens') for c in 'hl'):
                    assert [gsval(mfo, c, 'chosens') for c in 'hl'].count(True) == 2  # can't choose only one of a pair of abs
                    if cfgfo.get('include_previously_chosen'):
                        chosen_mfos.append(mfo)
                    all_chosen_seqs.add(tuple(gsval(mfo, c, 'input_seqs_aa') for c in 'hl'))
                    if tdbg:
                        print '        adding previously-chosen ab: %s' % ' '.join(gsval(mfo, c, 'unique_ids') for c in 'hl')
        if 'droplet-ids' in cfgfo:  # add some specific seqs
            for mfo in metric_pairs:
                did = get_joint_did(mfo)
                if did in cfgfo['droplet-ids']:
                    chosen_mfos.append(mfo)
                    all_chosen_seqs.add(tuple(gsval(mfo, c, 'input_seqs_aa') for c in 'hl'))
                    if tdbg:
                        print '        chose ab with droplet id %s' % did
        for ctk, ntk in [('cell-types', ctkey()), ('min-umis', 'umis')]:
            if len(metric_pairs) > 0 and ctk in cfgfo and ntk not in metric_pairs[0]['h']:
                print '  %s \'%s\' in cfgfo but \'%s\' info not in annotation' % (utils.color('yellow', 'warning'), ctk, ntk)
        if 'cell-types' in cfgfo and len(metric_pairs) > 0 and ctkey() in metric_pairs[0]['h']:
            def keepfcn(m): return all(gsval(m, c, ctkey()) in cfgfo['cell-types'] for c in 'hl')  # kind of dumb to check both, they should be the same, but whatever it'll crash in the debug printing below if they're different
            n_before = len(metric_pairs)
            metric_pairs = [m for m in metric_pairs if keepfcn(m)]
            if tdbg and n_before - len(metric_pairs) > 0:
                print '          skipped %d with cell type not among %s' % (n_before - len(metric_pairs), cfgfo['cell-types'])
        if 'min-umis' in cfgfo and len(metric_pairs) > 0 and 'umis' in metric_pairs[0]['h']:
            def keepfcn(m):
                if args.queries_to_include is not None and any(gsval(m, c, 'unique_ids') in args.queries_to_include for c in 'hl'):
                    return True
                return sumv(m, 'umis') > cfgfo['min-umis']  # queries_to_include probably won't have umis set, but still want to keep them
            n_before = len(metric_pairs)
            metric_pairs = [m for m in metric_pairs if keepfcn(m)]
            if tdbg and n_before - len(metric_pairs) > 0:
                print '          skipped %d with umis less than %d' % (n_before - len(metric_pairs), cfgfo['min-umis'])
        if 'min-median-nuc-shm-%' in cfgfo and len(metric_pairs) > 0:
            median_shm = numpy.median([sum_nuc_shm_pct(m) for m in metric_pairs])
            skip_family = median_shm < cfgfo['min-median-nuc-shm-%']
            if tdbg:
                print '          %s family: median h+l nuc shm %.2f%% %s than %.2f%%' % (utils.color('yellow', 'skipping entire') if skip_family else 'keeping', median_shm, 'less' if skip_family else 'greater', cfgfo['min-median-nuc-shm-%'])
            if skip_family:
                return []
        if 'max-ambig-positions' in cfgfo:  # max number of ambiguous amino acid positions summed over h+l
            def keepfcn(m):
                return sum(nambig(m, c) for c in 'hl') <= cfgfo['max-ambig-positions']
            n_before = len(metric_pairs)
            metric_pairs = [m for m in metric_pairs if keepfcn(m)]
            if tdbg and n_before - len(metric_pairs):
                print '          skipped %d with too many ambiguous bases (>%d)' % (n_before - len(metric_pairs), cfgfo['max-ambig-positions'])
        if 'similar-to-droplet-ids' in cfgfo:  # add seqs similar to some specific seqs
            for refid, n_take in cfgfo['similar-to-droplet-ids']:
                rmfos = [m for m in metric_pairs if get_joint_did(m)==refid]
                if len(rmfos) > 0:  # if <refid> is in the family
                    handle_droplet_sim_choice(refid, n_take, utils.get_single_entry(rmfos))

        if len(metric_pairs) == 0:
            return []

        if finished():
            return chosen_mfos

        # maybe add the unobserved cons/naive seqs
        for stype in ['cons', 'naive']:
            if cfgfo['include-unobs-%s-seqs'%stype][iclust]:
                add_unobs_seq(stype, metric_pairs, chosen_mfos, all_chosen_seqs, tdbg=tdbg)  # well, doesn't necessarily add it, but at least checks to see if we should
        if finished():
            return chosen_mfos

        # actually choose them, sorted by the various specified vars
        for sortvar, vcfg in cfgfo['vars'].items():
            n_prev_var_chosen, n_same_seqs, n_too_close, n_this_var_chosen = 0, 0, 0, 0
            sorted_mfos = metric_pairs
            sorted_mfos = sorted(sorted_mfos, key=lambda m: sumv(m, 'seq_mtps'), reverse=True)
            sorted_mfos = sorted(sorted_mfos, key=lambda m: sumv(m, sortvar), reverse=vcfg['sort']=='high')
            for mfo in sorted_mfos:
                if finished(tcfg=vcfg, n_newly_chosen=n_this_var_chosen):
                    break
                if mfo in chosen_mfos:
                    n_prev_var_chosen += 1
                    continue
                if in_chosen_seqs(all_chosen_seqs, mfo):
                    n_same_seqs += 1
                    continue
                if 'min-hdist-to-already-chosen' in cfgfo and too_close_to_chosen_seqs(all_chosen_seqs, mfo, cfgfo['min-hdist-to-already-chosen']):
                    n_too_close += 1
                    continue
                if any(gsval(mfo, c, 'has_shm_indels') for c in 'hl'):
                    print '          %s choosing ab with shm indel: the consensus sequence may or may not reflect the indels (see above). uids: %s %s' % (utils.color('yellow', 'warning'), gsval(mfo, 'h', 'unique_ids'), gsval(mfo, 'l', 'unique_ids'))
                chosen_mfos.append(mfo)
                all_chosen_seqs.add(tuple(gsval(mfo, c, 'input_seqs_aa') for c in 'hl'))
                n_this_var_chosen += 1  # number chosen from this sortvar

            if tdbg:
                print '        %s: chose %d%s%s%s' % (sortvar, n_this_var_chosen,
                                                    '' if n_prev_var_chosen==0 else ' (%d were in common with a previous var)'%n_prev_var_chosen,
                                                    '' if n_same_seqs==0 else ' (%d had seqs identical to previously-chosen ones)'%n_same_seqs,
                                                    '' if n_too_close==0 else ' (%d had seqs too close to previously-chosen ones)'%n_too_close)

        return chosen_mfos
    # ----------------------------------------------------------------------------------------
    def add_plotval_uids(iclust_plotvals, iclust_mfos, metric_pairs):
        def waschosen(m):
            return 'chosen' if all(gsval(m, c, 'unique_ids') in iclust_chosen_ids for c in 'hl') else 'nope'
        def ustr(m):
            rstr = ''
            if waschosen(m) == 'chosen':  # if this is commented, i think i can simplify this fcn a lot? UPDATE need the extra text for cases where lots of dots are on top of each other
                rstr = 'x'
            if args.queries_to_include is not None and all(gsval(m, c, 'unique_ids') in args.queries_to_include for c in 'hl'):
                common_chars = ''.join(c for c, d in zip(gsval(m, 'h', 'unique_ids'), gsval(m, 'l', 'unique_ids')) if c==d)
                common_chars = common_chars.rstrip('-ig')
                if len(common_chars) > 0:
                    rstr += ' ' + common_chars
                else:
                    rstr += ' ' + ' '.join(gsval(m, c, 'unique__ids') for c in 'hl')
            return None if rstr == '' else rstr
        observed_mfos = [m for m in iclust_mfos if m['seqtype'] == 'observed']
        iclust_chosen_ids = [gsval(m, c, 'unique_ids') for m in observed_mfos for c in 'hl']
        iclust_plotvals['uids'] = [ustr(m) for m in metric_pairs]
        iclust_plotvals['chosen'] = [waschosen(m) for m in metric_pairs]
    # ----------------------------------------------------------------------------------------
    def write_chosen_file(all_chosen_mfos, hash_len=8):
        # ----------------------------------------------------------------------------------------
        def getofo(mfo):
            ofo = collections.OrderedDict([('iclust', mfo['iclust'])])
            if mfo['seqtype'] == 'observed':
                ofo.update([(c+'_id', gsval(mfo, c, 'unique_ids')) for c in 'hl'])
                for kn in ['aa-cfrac', 'shm-aa', 'aa-cdist'] + [m for m in args.selection_metrics_to_calculate if m != 'cons-dist-aa']:
                    ofo.update([(kn, p_gsval(mfo, kn))])
            else:
                def gid(mfo, c):
                    hstr = utils.uidhashstr(getseq(mfo, c, aa=True))[:hash_len]
                    return '%s-%s-%d-%s' % (hstr, mfo['seqtype'], mfo['iclust'], mfo[c]['loci'][0])  # NOTE would be nice to use subj here, but i don't have it added to input meta info (yet)
                ofo.update([(c+'_id', gid(mfo, c)) for c in 'hl'])
            ofo.update([(c+'_family_size', len(mfo[c]['unique_ids'])) for c in 'hl'])
            ofo.update([(c+'_'+r+'_gene' , mfo[c][r+'_gene']) for r in utils.regions for c in 'hl'])
            ofo.update([(c+'_locus', mfo[c]['loci'][0]) for r in utils.regions for c in 'hl'])
            if mfo['seqtype'] == 'observed':
                okeys = [('has_shm_indels', None), ('aa-cfrac', None), ('aa-cdist', None), ('shm-aa', None), ('seq_nuc', 'input_seqs'), ('seq_aa', 'input_seqs_aa')]
                if any(ctkey() in mfo[c] for c in 'hl'):
                    okeys.insert(1, ('cell_type', ctkey()))
                for ok, lk in okeys:
                    ofo.update([(c+'_'+ok, gsval(mfo, c, utils.non_none([lk, ok]))) for c in 'hl'])
            else:
                for tch in 'hl':
                    ofo[tch+'_seq_aa'] = getseq(mfo, tch, aa=True)
                    ofo[tch+'_seq_nuc'] = getseq(mfo, tch, aa=False)
                    ofo[tch+'_has_shm_indels'] = mfo[tch+'_use_input_seqs']
            if mfo['seqtype'] == 'observed':  # check that the aa seqs are actually translations of the nuc seqs (for unobs cons seqs, we expect them to differ) NOTE i don't know if this is really worthwhile long term, but it makes me feel warm and fuzzy atm that it's here
                for tch in 'hl':
                    if utils.ltranslate(ofo[tch+'_seq_nuc']) != ofo[tch+'_seq_aa']:
                        print '  %s aa seq not translation of nuc seq for %s %s:' % (utils.color('yellow', 'warning'), tch, ofo[tch+'_id'])
                        utils.color_mutants(utils.ltranslate(ofo[tch+'_seq_nuc']), ofo[tch+'_seq_aa'], amino_acid=True, print_result=True, extra_str='        ')
            return ofo
        # ----------------------------------------------------------------------------------------
        print '      writing %d chosen abs to %s' % (len(all_chosen_mfos), args.chosen_ab_fname)
        with open(args.chosen_ab_fname, 'w') as cfile:
            outfos, fieldnames = [], None
            for mfo in all_chosen_mfos:
                outfos.append(getofo(mfo))
                if fieldnames is None or len(outfos[-1].keys()) > len(fieldnames):
                    fieldnames = outfos[-1].keys()
            if len(all_chosen_mfos) > 0:
                writer = csv.DictWriter(cfile, fieldnames)
                writer.writeheader()
                for ofo in outfos:
                    writer.writerow(ofo)
    # ----------------------------------------------------------------------------------------
    def print_dbg(metric_pairs, iclust_mfos, print_nuc_seqs=True):
        # ----------------------------------------------------------------------------------------
        def init_xtras():
            xtra_heads = [(ctkey(), ['cell', 'type']), ('umis', ['umis', 'h+l']), ('c_genes', ['c', 'gene']), ('affinities', ['affin', 'ity'])]
            if 'meta-info-print-keys' in cfgfo:
                xtra_heads += [(k, l if isinstance(l, list) else [l, '']) for k, l in cfgfo['meta-info-print-keys']]
            xtra_heads += [(h, [h, 'sum']) for h in smheads]
            xheads, xtrafo, xlens = [[], []], [], {}
            for xn, xh in xtra_heads:
                if all(gsval(mpfo, c, xn, no_fail=True) is None for mpfo in metric_pairs for c in 'hl'):
                    continue
                xtrafo.append(xn)
                ctlens = [utils.len_excluding_colors(single_xstr(m, xn, no_len=True)) for m in metric_pairs] # for c in 'hl']
                xlens[xn] = max([len(h) for h in xh] + ctlens)
                xheads = [x + [utils.wfmt(s, xlens[xn])] for x, s in zip(xheads, xh)]
            return xtrafo, xheads, xlens
        # ----------------------------------------------------------------------------------------
        def neut_col(mk, cg, tlen):
            if cg in [None, 'None']: return ' ' * tlen
            cg = float(cg)
            if 'supernatant-' in mk:
                tcol, cgstr = ('blue', '-') if cg < 0 else (None, '%.0f' % cg)
                if cg > 50: tcol = 'yellow'
                if cg > 75: tcol = 'red'
            elif 'ic50-' in mk:
                if cg > 9999:
                    tcol, cgstr = ('blue', '-')
                else:
                    tcol, cgstr = None, utils.wfmt(utils.round_to_n_digits(cg, 3), 1, fmt='.0f' if cg > 10 else '.1f')
                if cg < 1000: tcol = 'yellow'
                if cg < 100: tcol = 'red'
                if cg < 10: tcol = 'red_bkg'
            else:
                assert False
            return utils.color(tcol, cgstr, width=tlen)
        # ----------------------------------------------------------------------------------------
        def single_xstr(mpfo, xky, no_len=False):  # don't try to condense these into a block, they're too different
            def lenfcn(): return 1 if no_len else xlens.get(xky, 7)  # maybe should only have .get and 7 for smheads?
            if xky == ctkey():
                ctval = utils.get_single_entry(list(set(gsval(mpfo, c, ctkey()) for c in 'hl')))
                return utils.wfmt(utils.non_none([ctval, '?']), lenfcn())
            elif xky == 'umis':
                uvals = [gsval(mpfo, c, 'umis') for c in 'hl']
                return utils.wfmt('?' if None in uvals else sum(uvals), lenfcn())
            elif xky == 'c_genes':
                cg = gsval(mpfo, 'h', 'c_genes')
                return utils.wfmt('?' if cg in [None, 'None'] else cg.replace('IGH', ''), lenfcn())
            elif xky == 'affinities':
                affy = utils.get_single_entry(list(set([gsvstr(gsval(mpfo, c, 'affinities'), 'affinities') for c in 'hl'])))
                return utils.wfmt(affy, lenfcn())
            elif 'meta-info-print-keys' in cfgfo and xky in [k for k, _ in cfgfo['meta-info-print-keys']]:
                mv = utils.get_single_entry(list(set([gsval(mpfo, c, xky) for c in 'hl'])))
                if 'supernatant-' in xky or 'ic50-' in xky:  # colors that make sense for % neut values
                    mv = neut_col(xky, mv, lenfcn())
                elif xky == 'alternate-uids':
                    mv = utils.wfmt('' if mv is None else mv, lenfcn())
                return mv
            elif xky in smheads:
                return utils.wfmt(gsvstr(sumv(mpfo, xky), xky), lenfcn())
            else:
                print xky, cfgfo['meta-info-print-keys']
                assert False
        # ----------------------------------------------------------------------------------------
        def get_xstrs(mpfo):
            xstr = []  # don't try to condense these into a block, they're too different
            if ctkey() in xtrafo:
                xstr.append(single_xstr(mpfo, ctkey()))
            if 'umis' in xtrafo:
                xstr.append(single_xstr(mpfo, 'umis'))
            if 'c_genes' in xtrafo:
                xstr.append(single_xstr(mpfo, 'c_genes'))
            if 'affinities' in xtrafo:
                xstr.append(single_xstr(mpfo, 'affinities'))
            if 'meta-info-print-keys' in cfgfo:
                for mk in [k for k, _ in cfgfo['meta-info-print-keys'] if k in xtrafo]:
                    xstr.append(single_xstr(mpfo, mk))
            for sh in smheads:
                xstr.append(single_xstr(mpfo, sh))
            return xstr
        # ----------------------------------------------------------------------------------------
        def getcdist(mpfo, tch, frac=False):  # can't just use gsval() for cases where we used the "input" (indel'd) cons seq (although note that there's probably some other places where the orginal/indel-reversed version is used)
            defval = gsval(mpfo, tch, 'aa-c'+('frac' if frac else 'dist'))
            return local_hdist_aa(gsval(mpfo, tch, 'input_seqs_aa'), cons_mfo[tch+'_cseq_aa'], defval=defval, frac=frac)
        # ----------------------------------------------------------------------------------------
        def cstr(c, s2=None, aa=False):
            if not aa and not print_nuc_seqs: return ''
            cseq = cons_mfo['%s_cseq_%s' % (c, 'aa' if aa else 'nuc')]
            return utils.color_mutants(cseq, cseq if s2 is None else s2, amino_acid=aa, align_if_necessary=s2 is not None)  # align if necessary for naive seq, i.e. from nstr()
        # ----------------------------------------------------------------------------------------
        def nstr(c, aa=False):
            nseq = (h_atn if c=='h' else l_atn)['naive_seq'+('_aa' if aa else '')]
            return cstr(c, s2=nseq, aa=aa)
        # ----------------------------------------------------------------------------------------
        smheads = [m for m in args.selection_metrics_to_calculate if m != 'cons-dist-aa']
        xtrafo, xheads, xlens = init_xtras()
# ----------------------------------------------------------------------------------------
        print '  %s debug print needs updating to use new paired annotation rather than just adding h+l metrics (for now you need to set --run-single-chain-selection-metrics to get it to work at all)' % utils.wrnstr()
# TODO this doesn't really work cause you need to translate the tree, which isn't worth it -- just run single chain selection metrics, or update this fcn
        # for smetric in args.selection_metrics_to_calculate:
        #     for tmpntn in [h_atn, l_atn]:
        #         # calculate_individual_tree_metrics(smetric, [tmpntn], lb_tau=args.lb_tau) #, debug=True)
        #         inf_lines, true_lines = (None, [tmpntn]) if is_simu else (utils.get_annotation_dict([tmpntn]), None)
        #         add_smetrics(args, args.selection_metrics_to_calculate, inf_lines, args.lb_tau, true_lines_to_use=true_lines, treefname=args.treefname)
# ----------------------------------------------------------------------------------------

        if len(antn_pairs) > 1:
            utils.non_clonal_clusters((h_atn, l_atn), antn_pairs, dtype='lev', aa=True, labelstr='h+l', extra_str='              ')

        lstr = '%s %s' % (utils.locstr(h_atn['loci'][0]), utils.locstr(l_atn['loci'][0]))
        h_cshm, l_cshm = [lb_cons_seq_shm(l, aa=True) for l in [h_atn, l_atn]]
        cshm_str = '%2d %2d' % (h_cshm, l_cshm)
        sstr = ' %3d  %3d %3d' % (len(metric_pairs), len(h_atn['unique_ids']), len(l_atn['unique_ids']))
        gstrs = ['%s %s' % (utils.color_gene(h_atn[r+'_gene']), utils.color_gene(l_atn[r+'_gene']) if r!='d' else '') for r in utils.regions]
        gstr_len = max(utils.len_excluding_colors(s) for s in gstrs)  # don't really need this as long as it's the last column
        gstrs = ['%s%s' % (g, ' '*(gstr_len - utils.len_excluding_colors(g))) for g in gstrs]
        if any(m['seqtype']=='cons' for m in iclust_mfos):  # if the unobserved consensus was added for this cluster, we need to use the cons seq from cons_mfo for either of h/l that had enough shm indels that we used input seqs to calculate the cons seq (i.e. for which h/l_use_input_seqs was set)
            cons_mfo = utils.get_single_entry([m for m in iclust_mfos if m['seqtype']=='cons'])
        else:
            cons_mfo = get_unobs_mfo('cons', metric_pairs)  # if we didn't choose a cons seq, we need to get the cons seqs/info (since both aa and nuc "chosen" cons seqs can differ from the one in the annotation: both if there's lots of shm indels, and the nuc because of codon_len=3
        print ('             aa-cfrac (%%)      aa-cdist         droplet        contig indels%s       N     %%shm   N aa mutations     sizes            %s %s %s %s %s') % (' '.join(xheads[0]), utils.wfmt('genes    cons:', gstr_len), cstr('h', aa=True), cstr('l', aa=True), cstr('h'), cstr('l'))
        print ('             sum   h    l       h   l                           h  l   h l  %s  sum  h   l   nuc   cons.     obs.   both   h   l      %s %s %s %s %s') % (' '.join(xheads[1]), utils.wfmt('naive:', gstr_len), nstr('h', aa=True), nstr('l', aa=True), nstr('h'), nstr('l'))
        sorted_mfos = sorted(metric_pairs, key=lambda m: sumv(m, 'seq_mtps'), reverse=True)  # sort by sum of h and l sequence multiplicities
        last_cdist_str, last_mtpy_str, last_aa_shmstr = None, None, None
        for imp, mpfo in enumerate(sorted(sorted_mfos, key=lambda x: sum(getcdist(x, c, frac=True) for c in 'hl'))):  # would be nice to use sumv()
            hid, lid = [gsval(mpfo, c, 'unique_ids') for c in 'hl']
            dids, cids = zip(*[get_did(u, return_contigs=True) for u in (hid, lid)])
            didstr, cids = get_didstr(dids, cids, mpfo)
            indelstr = ' '.join(utils.color('red', 'y') if utils.per_seq_val(l, 'has_shm_indels', u) else ' ' for c, u, l in zip('hl', [hid, lid], [h_atn, l_atn]))
            h_seq, l_seq = [utils.color_mutants(cons_mfo[c+'_cseq_aa'], utils.per_seq_val(l, 'input_seqs_aa', u), amino_acid=True, align_if_necessary=True) for c, u, l in zip('hl', (hid, lid), (h_atn, l_atn))]
            h_nuc_seq, l_nuc_seq = '', ''
            if print_nuc_seqs:
                h_nuc_seq, l_nuc_seq = [utils.color_mutants(cons_mfo[c+'_cseq_nuc'], utils.per_seq_val(l, 'input_seqs', u), align_if_necessary=True) for c, u, l in zip('hl', (hid, lid), (h_atn, l_atn))]
            h_cfrac, l_cfrac = [getcdist(mpfo, c, frac=True) for c in 'hl']
            h_cdist, l_cdist = [getcdist(mpfo, c) for c in 'hl']
            aa_cdstr = '%4.1f %4.1f %4.1f   %4d%4d' % (100*sum([h_cfrac, l_cfrac]), 100*h_cfrac, 100*l_cfrac, h_cdist, l_cdist)
            h_mtpy, l_mtpy = [mtpys[c][gsval(mpfo, c, 'input_seqs_aa')] for c in 'hl']
            mtpstr = '%3d %3d %3d' % (sum((h_mtpy, l_mtpy)), h_mtpy, l_mtpy)
            aa_shmstr = '%2d %2d %2d' % (sumv(mpfo, 'shm-aa'), gsval(mpfo, 'h', 'shm-aa'), gsval(mpfo, 'l', 'shm-aa'))
            print '       %s  %s   %s %20s  %s  %s   %s' % (lstr if imp==0 else ' '*utils.len_excluding_colors(lstr),
                                                            aa_cdstr if aa_cdstr!=last_cdist_str else ' '*utils.len_excluding_colors(aa_cdstr),
                                                            utils.color('green', 'x') if mpfo in iclust_mfos else ' ',
                                                            didstr, cids[0], cids[1], indelstr),
            print ' %s %s %4.1f   %s  %s  %s    %s   %s %s %s %s' % (' '.join(get_xstrs(mpfo)),
                                                                     mtpstr if mtpstr != last_mtpy_str else ' '*utils.len_excluding_colors(mtpstr),
                                                                     sum_nuc_shm_pct(mpfo),
                                                                     cshm_str if imp==0 else ' '*len(cshm_str),
                                                                     aa_shmstr if aa_shmstr!=last_aa_shmstr else ' '*utils.len_excluding_colors(aa_shmstr),
                                                                     sstr if imp==0 else ' '*utils.len_excluding_colors(sstr), gstrs[imp] if imp<len(gstrs) else ' '*gstr_len,
                                                                     h_seq, l_seq, h_nuc_seq, l_nuc_seq)
            last_cdist_str, last_mtpy_str, last_aa_shmstr = aa_cdstr, mtpstr, aa_shmstr

        for gs in gstrs[imp+1:]:  # if the cluster was smaller than gstrs, need to print the extra gstrs (this shouldn't really ever happen unless i make gstrs much longer))
            print '%81s%s' % ('', gs)  # this width will sometimes be wrong
        print ''
    # ----------------------------------------------------------------------------------------
    def get_pantn(metric_pairs, h_atn):  # return a fake annotation <p_atn> with the sum/joint metrics in it
        # ----------------------------------------------------------------------------------------
        def translate_heavy_tree(htree):
            trns = [(gsval(m, 'h', 'unique_ids'), c) for m, c in zip(metric_pairs, p_atn['unique_ids'])]  # translation from hid to the new combined h+l id we just made
            translate_labels(htree, trns)
            htree.scale_edges(len(h_atn['seqs'][0]) / float(len(p_atn['seqs'][0])))
            return htree, htree.as_string(schema='newick')
        # ----------------------------------------------------------------------------------------
        p_atn = {}  # make a new fake annotation for the sequences that are in both h+l
        p_atn['unique_ids'] = [combid(m) for m in metric_pairs]
        p_atn['seqs'] = [sumv(m, 'seqs') for m in metric_pairs]
        p_atn['seqs_aa'] = [sumv(m, 'seqs_aa') for m in metric_pairs]
        p_atn['naive_seq'] = sumv(metric_pairs[0], 'naive_seq')
        p_atn['naive_seq_aa'] = sumv(metric_pairs[0], 'naive_seq_aa')  # NOTE it's *really* important you don't end up translating the sum'd naive seq since i don't think they necessarily get concat'd in frame
        p_atn['n_mutations'] = [sumv(m, 'n_mutations') for m in metric_pairs]
        p_atn['shm_aa'] = [sumv(m, 'shm_aa') for m in metric_pairs]
        p_atn['mut_freqs'] = [n / float(len(s)) for n, s in zip(p_atn['n_mutations'], p_atn['seqs'])]
        cpkeys = ['affinities' if args.affinity_key is None else args.affinity_key]
        if is_simu:
            _, p_atn['tree'] = translate_heavy_tree(get_dendro_tree(treestr=h_atn['tree']))
            cpkeys.append('min_target_distances')
        for tk in [k for k in cpkeys if k in h_atn]:
            p_atn[tk] = [h_atn[tk][m['h_iseq']] for m in metric_pairs]
        return p_atn
# ----------------------------------------------------------------------------------------
# ----------------------------------------------------------------------------------------
# ----------------------------------------------------------------------------------------
# # old way of just summing h+l metrics (don't want to do this):
#         p_atn['tree-info'] = {'lb' : {}}
#         if args.treefname is not None:
#             dtree, treestr = translate_heavy_tree(get_dendro_tree(treestr=h_atn['tree-info']['lb']['tree']))
#         else:
#             print '    getting fasttree (which may not be what you want)'
#             dtree = get_fasttree_tree([{'name' : combid(mfo), 'seq' : sumv(mfo, 'seqs')} for mfo in metric_pairs], naive_seq=p_atn['naive_seq'])  # NOTE kind of duplicates get_trees_for_annotations() (but i don't want to use that function because it requires a <line> whereas i went to great pains to rewrite this fcn here to not have a real/complete line for the h+l sequences
#             treestr = dtree.as_string(schema='newick')  # get this before the dummy branch stuff to make more sure it isn't modified
#         p_atn['tree-info']['lb']['tree'] = treestr
#         p_atn['tree-info']['lb']['aa-tree'] = get_aa_tree(dtree, p_atn).as_string(schema='newick')
#         for b_mtr in args.selection_metrics_to_calculate + ['shm', 'shm-aa']:
#             sum_mtr = 'sum-%s' % b_mtr
#             p_atn['tree-info']['lb'][sum_mtr] = {}
#             for mfo in metric_pairs:
#                 # if b_mtr == 'sum-aa-lbr':
#                 print b_mtr, gsval(mfo, 'h', 'unique_ids'), gsval(mfo, 'h', b_mtr), gsval(mfo, 'l', b_mtr), sumv(mfo, b_mtr)
#                 sum_mval = sumv(mfo, b_mtr)
#                 if sum_mval is None:
#                     continue
#                 pid = p_atn['unique_ids'][mfo['h_iseq']]
#                 p_atn['tree-info']['lb'][sum_mtr][pid] = sum_mval
#         return p_atn
    # ----------------------------------------------------------------------------------------
    def get_mtpys(metric_pairs):  # NOTE this is the sum of utils.get_multiplicity() over identical sequences
        mtpys = {}
        for c in 'hl':
            seqlist = [gsval(m, c, 'input_seqs_aa') for m in metric_pairs for _ in range(gsval(m, c, 'multipy'))]
            mtpys[c] = {s : seqlist.count(s) for s in set(seqlist)}
        return mtpys

    # ----------------------------------------------------------------------------------------
    import paircluster  # if you import it up top it fails, and i don't feel like fixing the issue
    debug = args.debug or args.debug_paired_clustering  # not is_simu or
    if 'cons-dist-aa' not in args.selection_metrics_to_calculate:
        print '  %s \'cons-dist-aa\' not in --selection-metrics-to-calculate, so things may not work' % utils.color('yellow', 'warning')
    all_chosen_mfos = []
    cfgfo = read_cfgfo()
    antn_pairs = []
    for lpair in [lpk for lpk in utils.locus_pairs[ig_or_tr] if tuple(lpk) in lp_infos]:
        antn_pairs += paircluster.find_cluster_pairs(lp_infos, lpair, min_cluster_size=min_cluster_size)  # , required_keys=['tree-info']
    antn_pairs = sorted(antn_pairs, key=lambda x: sum(len(l['unique_ids']) for l in x), reverse=True)  # sort by the sum of h+l ids (if i could start over i might sort by the number of common ids)
    # all_plotvals = {k : [] for k in ('h_aa-cfrac', 'l_aa-cfrac')}
    pair_antns = []
    if debug:
        print '    %d h/l pairs: %s' % (len(antn_pairs), ',  '.join(' '.join(str(len(l['unique_ids'])) for l in p) for p in antn_pairs))
        print '      key: %s %s %s (empty/blank numbers are same as previous line)' % (utils.color('red', 'queries-to-include'), utils.color('blue_bkg', 'previously chosen'), utils.color('red', utils.color('blue_bkg', 'both')))
    for iclust, (h_atn, l_atn) in enumerate(antn_pairs):
        for ltmp in (h_atn, l_atn):
            utils.add_seqs_aa(ltmp)
            utils.add_naive_seq_aa(ltmp)
        metric_pairs = []
        for hid, pids in zip(h_atn['unique_ids'], h_atn['paired-uids']):
            if pids is None or len(pids) == 0:  # should only have the latter now (set with .get() call in rewrite_input_metafo())
                continue
            lid = pids[0]
            if lid not in l_atn['unique_ids']:
                print '  paired light id %s missing' % lid
                continue
            mpfo = {'iclust' : iclust, 'seqtype' : 'observed'}
            for tch, uid, ltmp in zip(('h', 'l'), (hid, lid), (h_atn, l_atn)):
                mpfo[tch] = ltmp
                mpfo[tch+'_iseq'] = ltmp['unique_ids'].index(uid)
            metric_pairs.append(mpfo)
        pair_antns.append(get_pantn(metric_pairs, h_atn))
        if len(metric_pairs) == 0:
            continue
        mtpys = get_mtpys(metric_pairs)  # ick (this is used by fcns relying on scope)
        iclust_mfos = choose_abs(metric_pairs, iclust, tdbg=debug)
        if len(iclust_mfos) > 0:
            all_chosen_mfos += iclust_mfos
            for mfo in iclust_mfos:
                mfo['p_atn'] = pair_antns[-1]  # ick
            if debug:
                print '      chose %d total' % len(iclust_mfos)
        if debug:
            print_dbg(metric_pairs, iclust_mfos)  # note that this fcn uses a lot of local variables that we don't pass to it
    inf_lines, true_lines = (None, pair_antns) if is_simu else (utils.get_annotation_dict(pair_antns), None)
    add_smetrics(args, args.selection_metrics_to_calculate, inf_lines, args.lb_tau, true_lines_to_use=true_lines, treefname=args.treefname, base_plotdir=plotdir, ete_path=args.ete_path,
                 workdir=args.workdir, outfname=args.selection_metric_fname) #, debug=True)
# TODO will need these args in order to run gctree
                 # glfo=, gctree_outdir=None if args.outfname is None or not args.run_gctree else os.path.dirname(utils.fpath(args.outfname)),
    if args.chosen_ab_fname is not None:
        write_chosen_file(all_chosen_mfos)
    # if plotdir is not None:  # eh, maybe there isn't a big reason for an overall one
    #     lbplotting.plot_2d_scatter('h-vs-l-cfrac-iclust-all', plotdir, all_plotvals, 'l_aa-cfrac', 'light %s'%mstr, mstr, xvar='h_aa-cfrac', xlabel='heavy %s'%mstr, colorvar='chosen', stats='correlation')
