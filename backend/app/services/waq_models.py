"""
Registry of the DELWAQ model templates used by wq_functions.wqPreparation.
Generated from the original if/elif blocks. Each model lists its B1 substance file,
the processes it activates, its constants (name -> value, so names and values can
never drift apart), the hydrodynamic files used as segment functions and the extra
output parameters written to the his and map files.
"""
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class WaqModel:
    key: str                  # internal key, e.g. "simple-oxygen"
    ui_key: str               # key sent by the frontend, e.g. "Simple_Oxygen"
    title: str
    b1_file: str              # substance list in templates/waq
    substances: tuple         # substances offered in the "use for" table
    processes: tuple          # activated through CONSTANTS 'ACTIVE_<name>'
    constants: MappingProxyType
    segfunctions: tuple = ()  # (parameter name, key of the hyd file path in parameters)
    outputs: tuple = ()       # extra parameters in the his and map output


def _model(**kw) -> WaqModel:
    kw["constants"] = MappingProxyType(dict(kw["constants"]))
    return WaqModel(**kw)

MODELS = {
    'simple-oxygen': _model(
        key='simple-oxygen', ui_key='Simple_Oxygen',
        title='Simple oxygen (NH4, CBOD5, OXY, SOD)',
        b1_file='B1_simple_oxygen.inc',
        substances=('NH4', 'CBOD5', 'OXY', 'SOD'),
        processes=(
            'Nitrif_NH4', 'BODCOD', 'RearOXY', 'SedOXYDem', 'PosOXY', 'DynDepth', 'SaturOXY',
            'TotDepth', 'Veloc'
        ),
        constants={
            'RcNit': '0.1', 'RcBOD': '0.3', 'COXBOD': '1', 'OOXBOD': '5', 'CFLBOD': '0.3',
            'O2FuncBOD': '0', 'BOD5': '0', 'BODu': '0', 'SWRear': '1', 'KLRear': '1', 'fSOD': '0',
            'RcSOD': '0.1', 'VWind': '3',
        },
        segfunctions=(('Temp', 'tem_path'),),
        outputs=('DO',),
    ),
    'trace-metals': _model(
        key='trace-metals', ui_key='Trace_Metals',
        title='Trace metals As, Cu, Ni, Pb, Zn, DUFLOW Metal',
        b1_file='B1_trace_metals.inc',
        substances=(
            'ASWTOT', 'CUWTOT', 'NIWTOT', 'PBWTOT', 'POCW', 'AOCW', 'DOCW', 'SSW', 'ZNWTOT',
            'ASREDT', 'ASSTOT', 'ASSUBT', 'CUREDT', 'CUSTOT', 'CUSUBT', 'NIREDT', 'NISTOT',
            'NISUBT', 'PBREDT', 'PBSTOT', 'PBSUBT', 'DOCB', 'DOCSUB', 'POCB', 'POCSUB', 'S',
            'ZNREDT', 'ZNSTOT', 'ZNSUBT'
        ),
        processes=('HydDuflow', 'Metal'),
        constants={
            'aAs': '0', 'aCu': '1.25', 'aNi': '0', 'aPb': '1.176', 'aZn': '1.358', 'bAs': '0',
            'bCu': '-5.39E-05', 'bNi': '0', 'bPb': '-6.59E-05', 'bZn': '-8.06E-05', 'alfa': '0.5',
            'CUSulf': '0.003', 'DZ1': '0.01', 'DZ2': '0.09', 'Ez0': '5E-05', 'fbx': '10',
            'fc': '0.52', 'fwx': '30', 'KAsDOC': '1E-05', 'KAsSS': '0.003', 'KAsSSW': '0.1',
            'KCuDOC': '0.5', 'KCuSS': '0.085', 'KCuSSW': '0.05', 'KdAOC': '0.5', 'KHYDW': '0.001',
            'KHYDB': '5E-05', 'KDMINW': '0.04', 'KDMINB': '0.015', 'KNiDOC': '0.1',
            'KNiSS': '0.01', 'KNiSSW': '0.008', 'KPbDOC': '1.02', 'KPbSS': '0.231',
            'KPbSSW': '0.64', 'KZnDOC': '0.1', 'KZnSS': '0.02', 'KZnSSW': '0.22',
            'NIsulf': '0.025', 'Pbsulf': '0.003', 'POR': '0.8', 'RHOANO': '2600000',
            'RHOORG': '1000000', 'Vsp': '0.4', 'Vss': '1.5', 'Vsn': '0.7', 'Znsulf': '0.01',
            'Cl': '200', 'pHb': '6', 'PAOC': '1', 'Fres': '20', 'ASatm': '0', 'CUatm': '0',
            'NIatm': '0', 'Pbatm': '0', 'Znatm': '0',
        },
        outputs=(
            'Z', 'Q', 'As', 'dt', 'dx', 'V', 'Wf', 'Wd', 'SSB', 'FCSSW', 'FCSSB', 'FOMW', 'FSSW',
            'FOMB', 'FSSB', 'RHOSSW', 'RHOSSB', 'VR', 'VS', 'FSPOC', 'EZ1', 'EZ2', 'KASSSB',
            'KCUSSB', 'KNISSB', 'KPBSSB', 'KZNSSB', 'ASWDIS', 'ASWDOC', 'ASWSS', 'ASSDIS', 'ASSDOC',
            'ASSSS', 'ASREDDOC', 'ASREDSS', 'ASREDDIS', 'ASSUBDIS', 'ASSUBDOC', 'ASSUBSS', 'CUWDIS',
            'CUWDOC', 'CUWSS', 'CUSDIS', 'CUSDOC', 'CUSSS', 'CUREDDOC', 'CUREDSS', 'CUREDDIS',
            'CUSUBDIS', 'CUSUBDOC', 'CUSUBSS', 'NIWDIS', 'NIWDOC', 'NIWSS', 'NISDIS', 'NISDOC',
            'NISSS', 'NIREDDOC', 'NIREDSS', 'NIREDDIS', 'NISUBDIS', 'NISUBDOC', 'NISUBSS', 'PBWDIS',
            'PBWDOC', 'PBWSS', 'PBSDIS', 'PBSDOC', 'PBSSS', 'PBREDDOC', 'PBREDSS', 'PBREDDIS',
            'PBSUBDIS', 'PBSUBDOC', 'PBSUBSS', 'ZNWDIS', 'ZNWDOC', 'ZNWSS', 'ZNSDIS', 'ZNSDOC',
            'ZNSSS', 'ZNREDDOC', 'ZNREDSS', 'ZNREDDIS', 'ZNSUBDIS', 'ZNSUBDOC', 'ZNSUBSS', 'MASATM',
            'MASSED', 'MASRES', 'MASDIF1', 'MASDIF2', 'MASDIF3', 'MASPSAD1', 'MASPSAD2', 'MASPSAD3',
            'MCUATM', 'MCUSED', 'MCURES', 'MCUDIF1', 'MCUDIF2', 'MCUDIF3', 'MCUPSAD1', 'MCUPSAD2',
            'MCUPSAD3', 'MNIATM', 'MNISED', 'MNIRES', 'MNIDIF1', 'MNIDIF2', 'MNIDIF3', 'MNIPSAD1',
            'MNIPSAD2', 'MNIPSAD3', 'MPBATM', 'MPBSED', 'MPBRES', 'MPBDIF1', 'MPBDIF2', 'MPBDIF3',
            'MPBPSAD1', 'MPBPSAD2', 'MPBPSAD3', 'MZNATM', 'MZNSED', 'MZNRES', 'MZNDIF1', 'MZNDIF2',
            'MZNDIF3', 'MZNPSAD1', 'MZNPSAD2', 'MZNPSAD3', 'ASDISW', 'ASDISS', 'ASDISRED', 'ASSSW',
            'ASSSRED', 'CUDISW', 'CUDISS', 'CUDISRED', 'CUSSW', 'CUSSRED', 'NIDISW', 'NIDISS',
            'NIDISRED', 'NISSW', 'NISSRED', 'PBDISW', 'PBDISS', 'PBDISRED', 'PBSSW', 'PBSSRED',
            'ZNDISW', 'ZNDISS', 'ZNDISRED', 'ZNSSW', 'ZNSSRED'
        ),
    ),
    'oxygen-bod-water': _model(
        key='oxygen-bod-water', ui_key='Oxygen_BOD',
        title='Oxygen and BOD, water column only',
        b1_file='B1_bod_water.inc',
        substances=('OXY', 'CBOD5'),
        processes=('RearOXY', 'BODCOD', 'DynDepth', 'SaturOXY', 'TotDepth', 'Veloc'),
        constants={
            'VWind': '3', 'SWRear': '1', 'KLRear': '1', 'RcBOD': '0.3', 'Phyt': '0',
        },
        segfunctions=(('Salinity', 'sal_path'), ('Temp', 'tem_path')),
        outputs=(
            'Depth', 'Temp', 'Velocity', 'VWind', 'SWRear', 'KLRear', 'TCRear', 'SaturOXY',
            'Salinity', 'RCREAR', 'SatPercOXY', 'SwOXYDem', 'RcBOD', 'TcBOD', 'BOD5', 'BODu',
            'fSOD', 'RcSOD', 'TcSOD', 'TotalDepth', 'COXSOD', 'OOXSOD', 'VSedBOD5', 'Tau',
            'TaucSBOD', 'MinDepth', 'PSedBOD5', 'fSedBOD5', 'fSedSOD', 'Cl', 'SWSatOXY', 'CHEZY'
        ),
    ),
    'cadmium': _model(
        key='cadmium', ui_key='Cadmium',
        title='Cadmium with suspended sediment (IM1)',
        b1_file='B1_cadmium.inc',
        substances=('IM1', 'Cd', 'IM1S1', 'CdS1'),
        processes=(
            'Compos', 'Sed_IM1', 'S12TraIM1', 'S1_Comp', 'Sed_Cd', 'S12TraCd', 'CalTau', 'DynDepth',
            'Res_DM', 'PartWK_Cd', 'PartS1_Cd', 'Veloc', 'Chezy', 'TotDepth'
        ),
        constants={
            'TaucSIM1': '0.1', 'ZResDM': '0', 'TaucRS1DM': '0.2',
        },
    ),
    'eutrophication': _model(
        key='eutrophication', ui_key='Eutrophication',
        title='Eutrophication, DUFLOW Eutr1a',
        b1_file='B1_eu_1a.inc',
        substances=('A', 'DP', 'NORG', 'NH4', 'NO3'),
        processes=('HydDuflow', 'Eutr1a'),
        constants={
            'UMAX': '1', 'ALFA': '0.02', 'IOPT': '40', 'PIOPT': '1', 'ACA': '30', 'KLOSS': '0.1',
            'KMIN': '0.1', 'KNIT': '0.2', 'KDEN': '0.05', 'KP': '0.005', 'KN': '0.01', 'EPS0': '2',
            'EPSALG': '0.016', 'THGA': '1.04', 'THMIN': '1.04', 'THNIT': '1.06', 'THDEN': '1.06',
            'VSO': '1', 'ANC': '0.176', 'APC': '0.024', 'ISOM': '100', 'L': '12', 'T': '20',
            'NFLUX': '0', 'PFLUX': '0',
        },
        outputs=(
            'Z', 'Q', 'As', 'dt', 'dx', 'V', 'Wf', 'Wd', 'FT', 'FN', 'IOMAX', 'CHLA', 'ETOT', 'H1',
            'fl2', 'f', 'ALFA1', 'GA', 'KMINT', 'KNITT', 'KDENT', 'KJN', 'NTOT', 'PTOT'
        ),
    ),
    'conservative-tracers': _model(
        key='conservative-tracers', ui_key='Conservative_Tracers',
        title='Conservative and decaying tracers with water age',
        b1_file='B1_conservative.inc',
        substances=('cTR1', 'cTR2', 'cTR3', 'dTR1', 'dTR2', 'dTR3'),
        processes=('Age1', 'Age2', 'Age3'),
        constants={
            'RcDecTR1': '0.01', 'RcDecTR3': '0.01',
        },
    ),
    'suspend-sediment': _model(
        key='suspend-sediment', ui_key='Suspend_Sediment',
        title='Suspended sediment, three fractions',
        b1_file='B1_suspend_sediment.inc',
        substances=('IM1', 'IM2', 'IM3', 'IM1S1', 'IM2S1', 'IM3S1'),
        processes=(
            'Compos', 'Sed_IM1', 'S12TraIM1', 'S1_Comp', 'Sed_IM2', 'S12TraIM2', 'Sed_IM3',
            'S12TraIM3', 'CalTau', 'DynDepth', 'Res_DM', 'Veloc', 'Chezy', 'TotDepth'
        ),
        constants={
            'VSedIM1': '0.1', 'TaucSIM1': '0.1', 'VSedIM2': '0.1', 'TaucSIM2': '0.1',
            'VSedIM3': '0.1', 'TaucSIM3': '0.1', 'TaucRS1DM': '0.2',
        },
    ),
    'trwp-metals': _model(
        key='trwp-metals', ui_key='Metals_Tire_Road',
        title='Tyre and road wear particles (TRWP) with metals',
        b1_file='B1_trwp_metals.inc',
        substances=(
            'Continuity', 'cTR1', 'dTR1', 'ModTemp', 'IM1', 'Cd', 'Cr', 'Cu', 'Ni', 'Pb', 'Zn',
            'Tyre1', 'Tyre2', 'Tyre3', 'Tyre4', 'TyreAgg11', 'TyreAgg12', 'TyreAgg13', 'TyreAgg21',
            'TyreAgg22', 'TyreAgg23', 'TyreAgg31', 'TyreAgg32', 'TyreAgg33', 'TyreAgg41',
            'TyreAgg42', 'TyreAgg43', 'IM1S1', 'IM1S2', 'CdS1', 'CdS2', 'CrS1', 'CrS2', 'CuS1',
            'CuS2', 'NiS1', 'NiS2', 'PbS1', 'PbS2', 'ZnS1', 'ZnS2', 'TAggSed11', 'TAggSed12',
            'TAggSed13', 'TAggSed21', 'TAggSed22', 'TAggSed23', 'TAggSed31', 'TAggSed32',
            'TAggSed33', 'TAggSed41', 'TAggSed42', 'TAggSed43'
        ),
        processes=(
            'Emersion', 'ResTim', 'HDisperVel', 'HDisperAdd', 'Evap_Conti', 'Age1', 'Decay1',
            'Temperatur', 'MakOOC', 'Compos', 'Res_Buffer', 'S12TraIM1', 'Sed_IM1', 'AtmDep_IM1',
            'Dfwast_IM1', 'Secchi', 'Dredge', 'IM_Floceq', 'TraSe2_IM1', 'MakOOCS1', 'S1_Comp',
            'S2_Comp', 'Sed_Cd', 'S12TraCd', 'AtmDep_Cd', 'Dfwast_Cd', 'Sed_Cr', 'S12TraCr',
            'AtmDep_Cr', 'Dfwast_Cr', 'Sed_Cu', 'S12TraCu', 'AtmDep_Cu', 'Dfwast_Cu', 'Sed_Ni',
            'S12TraNi', 'AtmDep_Ni', 'Dfwast_Ni', 'Sed_Pb', 'S12TraPb', 'AtmDep_Pb', 'Dfwast_Pb',
            'Sed_Zn', 'S12TraZn', 'AtmDep_Zn', 'Dfwast_Zn', 'DynDepth', 'TotDepth', 'Meteo',
            'CalTau', 'S12TraIM2', 'S12TraIM3', 'Res_DM', 'Extinc_VLG', 'PartWK_Cd', 'PartS1_Cd',
            'PartWK_Cr', 'PartS1_Cr', 'PartWK_Cu', 'PartS1_Cu', 'PartWK_Ni', 'PartS1_Ni',
            'PartWK_Pb', 'PartS1_Pb', 'PartWK_Zn', 'PartS1_Zn', 'Veloc', 'Chezy', 'PROPSING',
            'PROPTAGG', 'HTRAGG', 'SEDTYRE', 'SEDTAGG', 'SUMTRWP'
        ),
        constants={
            'ZThreshold': '0.01', 'Dfact_a': '10', 'Dfact_b': '0.8', 'Dfact_c': '1.2',
            'Dback': '10', 'Dmin': '0', 'Dmax': '1000', 'AddDispH': '10', 'fEvapConti': '-999',
            'sw1AtmDCon': '1', 'sw2AtmDCon': '0', 'RcDecTR1': '0.01', 'dDecdTR1': '0.01',
            'NatTemp': '15', 'CP': '4183', 'SwitchTemp': '1', 'FactRcHeat': '1', 'ZHeatExch': '0',
            'SwTempDF': '0', 'IM2': '0', 'IM3': '0', 'FCSEDIM1': '-999', 'FCSEDIM2': '0',
            'FCSEDIM3': '0', 'DMCFOOC': '2.5', 'DOC': '0', 'Phyt': '0', 'IM2S1': '0', 'IM3S1': '0',
            'IM2S2': '0', 'IM3S2': '0', 'TauShields': '0.2', 'GRAIN50': '0.0003', 'GRAV': '9.8',
            'KinViscos': '0.000001', 'RHOSAND': '2600000', 'RhoWater': '-999', 'PORS2': '0',
            'ThickS2': '0.5', 'MinDepth': '0.1', 'MaxResPup': '1.0E+20', 'TaucRS1IM3': '0.2',
            'DMS2': '0.000001', 'FrTIMS2': '0', 'FrIM1S2': '0', 'FrIM1S3': '0', 'fBurS1DM': '0',
            'fBurS2DM': '0', 'fDigS1DM': '0', 'fDigS2DM': '0', 'SWDigS1': '0', 'ZSedIM1': '0',
            'VSedIM1': '0.1', 'TaucSIM1': '0.1', 'FrIM1SedS2': '0', 'fAtmDepIM1': '-999',
            'sw1AtmDIM1': '1', 'sw2AtmDIM1': '0', 'fDfwastIM1': '-999', 'sw1DfwaIM1': '1',
            'sw2DfwaIM1': '0', 'PAConstant': '1.7', 'basin_no': '0', 'no_basin': '-999',
            '*IM1': '1', '*IM2': '1', '*IM3': '1', '*IM1S1': '1', '*IM2S1': '1', '*IM3S1': '1',
            '*IM1S2': '1', '*IM2S2': '1', '*IM3S2': '1', 'start_dr01': '0', 'start_dr02': '0',
            'freq__dr04': '0', 'freq__dr05': '0', 'freq__dr06': '0', 'freq__dr07': '0',
            'freq__dr08': '0', 'freq__dr09': '0', 'crit__dr01': '0', 'crit__dr02': '0',
            'crit__dr03': '0', 'crit__dr04': '0', 'crit__dr05': '0', 'crit__dr06': '0',
            'crit__dr07': '0', 'crit__dr08': '0', 'crit__dr09': '0', 'sws1s2dr01': '1',
            'sws1s2dr02': '1', 'sws1s2dr03': '1', 'sws1s2dr04': '1', 'sws1s2dr05': '1',
            'sws1s2dr06': '1', 'sws1s2dr07': '1', 'sws1s2dr08': '1', 'sws1s2dr09': '1',
            'seg___dr01': '0', 'seg___dr02': '0', 'seg___dr03': '0', 'seg___dr04': '0',
            'seg___dr05': '0', 'seg___dr06': '0', 'seg___dr07': '0', 'seg___dr08': '0',
            'seg___dr09': '0', 'speed_dr01': '0', 'speed_dr02': '0', 'speed_dr03': '0',
            'speed_dr04': '0', 'speed_dr05': '0', 'speed_dr06': '0', 'speed_dr07': '0',
            'speed_dr08': '0', 'speed_dr09': '0', 'relab_dr01': '0', 'relab_dr02': '0',
            'relab_dr03': '0', 'relab_dr04': '0', 'relab_dr05': '0', 'relab_dr06': '0',
            'relab_dr07': '0', 'relab_dr08': '0', 'relab_dr09': '0', 'SwFloceq': '0',
            'RcFloc': '2.31', 'RcBreakup': '2.31', 'VxRes0': '0', 'VxSedDum': '0', 'VxBur0': '0',
            'VxTur0': '0', 'VxDif0': '0', 'VxSep0': '0', 'FCSEDIM1S1': '-999', 'FCSEDIM2S1': '0',
            'FCSEDIM3S1': '0', 'DMCFOOCS': '1.7', 'OOCS1': '0', 'DetCS1': '0', 'AAPS1': '0',
            'DetNS1': '0', 'DetPS1': '0', 'DetSiS1': '0', 'OONS1': '0', 'PHYTS1': '0',
            'fSedIM2': '0', 'fSedIM3': '0', 'fSedPOCnoa': '0', 'fSedPHYT': '0',
            'fAtmDepCd': '-999', 'sw1AtmDCd': '1', 'sw2AtmDCd': '0', 'fDfwastCd': '-999',
            'sw1DfwaCd': '1', 'sw2DfwaCd': '0', 'QCrIM2': '0', 'QCrIM3': '0', 'QCrPOC': '0',
            'QCrPHYT': '0', 'QCrDMS2': '0', 'QCrDMS3': '0', 'fAtmDepCr': '-999', 'sw1AtmDCr': '1',
            'sw2AtmDCr': '0', 'fDfwastCr': '-999', 'sw1DfwaCr': '1', 'sw2DfwaCr': '0',
            'QCuIM2': '0', 'QCuIM3': '0', 'QCuPOC': '0', 'QCuPHYT': '0', 'fAtmDepCu': '-999',
            'sw1AtmDCu': '1', 'sw2AtmDCu': '0', 'fDfwastCu': '-999', 'sw1DfwaCu': '1',
            'sw2DfwaCu': '0', 'fAtmDepNi': '-999', 'sw1AtmDNi': '1', 'sw2AtmDNi': '0',
            'fDfwastNi': '-999', 'sw1DfwaNi': '1', 'sw2DfwaNi': '0', 'QPbIM2': '0', 'QPbIM3': '0',
            'QPbPOC': '0', 'QPbPHYT': '0', 'QPbDMS2': '0', 'QPbDMS3': '0', 'fAtmDepPb': '-999',
            'sw1AtmDPb': '1', 'sw2AtmDPb': '0', 'fDfwastPb': '-999', 'sw1DfwaPb': '1',
            'sw2DfwaPb': '0', 'fAtmDepZn': '-999', 'sw1AtmDZn': '1', 'sw2AtmDZn': '0',
            'fDfwastZn': '-999', 'sw1DfwaZn': '1', 'sw2DfwaZn': '0', 'Rad_1': '-999',
            'VWind_1': '-999', 'WinDir_1': '-999', 'RelHum_1': '-999', 'AirTemp_1': '-999',
            'AirPres_1': '-999', 'Cloud_1': '-999', 'Rad_2': '0', 'VWind_2': '0', 'WinDir_2': '0',
            'RelHum_2': '0', 'AirTemp_2': '0', 'AirPres_2': '0', 'Cloud_2': '0.5', 'Rad_3': '0',
            'VWind_3': '0', 'WinDir_3': '0', 'RelHum_3': '0', 'AirTemp_3': '0', 'AirPres_3': '0',
            'Cloud_3': '0.5', 'Rad_4': '0', 'VWind_4': '0', 'WinDir_4': '0', 'RelHum_4': '0',
            'AirTemp_4': '0', 'AirPres_4': '0', 'Cloud_4': '0.5', 'Rad_5': '0', 'VWind_5': '0',
            'WinDir_5': '0', 'RelHum_5': '0', 'AirTemp_5': '0', 'AirPres_5': '0', 'Cloud_5': '0.5',
            'Rad_6': '0', 'VWind_6': '0', 'WinDir_6': '-999', 'RelHum_6': '0', 'AirTemp_6': '0',
            'AirPres_6': '0', 'Cloud_6': '0', 'Rad_7': '0', 'VWind_7': '0', 'WinDir_7': '-999',
            'RelHum_7': '0', 'AirTemp_7': '0', 'AirPres_7': '0', 'Cloud_7': '0.5', 'Rad_8': '0',
            'VWind_8': '0', 'WinDir_8': '-999', 'RelHum_8': '0', 'AirTemp_8': '0',
            'AirPres_8': '0', 'Cloud_8': '0.5', 'Rad_9': '0', 'VWind_9': '0', 'WinDir_9': '0',
            'RelHum_9': '0', 'AirTemp_9': '0', 'AirPres_9': '0', 'Cloud_9': '0.5', 'Rad_10': '0',
            'VWind_10': '0', 'WinDir_10': '0', 'RelHum_10': '0', 'AirTemp_10': '0',
            'AirPres_10': '0', 'Cloud_10': '0.5', 'XMeteo1': '0', 'YMeteo1': '0', 'XMeteo2': '0',
            'YMeteo2': '0', 'XMeteo3': '0', 'YMeteo3': '0', 'XMeteo4': '0', 'YMeteo4': '0',
            'XMeteo5': '0', 'YMeteo5': '0', 'XMeteo6': '0', 'YMeteo6': '0', 'XMeteo7': '0',
            'YMeteo7': '0', 'XMeteo8': '0', 'YMeteo8': '0', 'XMeteo9': '0', 'YMeteo9': '0',
            'XMeteo10': '0', 'YMeteo10': '0', 'XYScaleFac': '1', 'NoMeteoSta': '1',
            'MeteoClcSW': '1', 'XSeg': '-999', 'YSeg': '-999', 'XDOCCd': '0.1', 'KdCdIM1': '130',
            'KdCdIM2': '130', 'DOCS1': '0', 'KdCdIM1S1': '130', 'KdCdIM2S1': '130',
            'XDOCCr': '0.18', 'KdCrIM1': '290', 'KdCrIM2': '290', 'KdCrIM1S1': '290',
            'KdCrIM2S1': '290', 'XDOCCu': '0.18', 'KdCuIM1': '50', 'KdCuIM2': '50',
            'XDOCPb': '0.18', 'KdPbIM1': '640', 'KdPbIM2': '640', 'KdPbIM1S1': '640',
            'KdPbIM2S1': '640', 'XDOCZn': '0.18', 'KdZnIM1': '110', 'KdZnIM2': '110',
            'DiamTyre1': '30', 'Dens_Tyre1': '1800', 'ShapeFac1': '0.8', 'DiamTyre2': '75',
            'Dens_Tyre2': '1800', 'ShapeFac2': '0.8', 'DiamTyre3': '125', 'Dens_Tyre3': '1800',
            'ShapeFac3': '0.8', 'DiamTyre4': '200', 'Dens_Tyre4': '1800', 'ShapeFac4': '0.8',
            'Diam_Susp1': '2', 'Dens_Susp1': '2650', 'Diam_Susp2': '16', 'Dens_Susp2': '2650',
            'Diam_Susp3': '63', 'Dens_Susp3': '2650', 'ShapeFacSu': '0.7', 'BioFilmThk': '0',
            'BioFilmDen': '1100', 'Efficiency': '0.001', 'SafeFactor': '0.05', 'VSedIM2': '0',
            'VSedIM3': '0',
        },
        outputs=(
            'Depth', 'ZThreshold', 'SwEmersion', 'ResTim', 'Dfact_a', 'Dfact_b', 'Dfact_c', 'Dback',
            'Dmin', 'Dmax', 'TotalDepth', 'Ddir1', 'AddDispH', 'HorzDispA', 'fEvapConti',
            'sw1AtmDCon', 'sw2AtmDCon', 'RcDecTR1', 'AgeTR1', 'dDecdTR1', 'NatTemp', 'VWind', 'CP',
            'SwitchTemp', 'FactRcHeat', 'ZHeatExch', 'SwTempDF', 'LocSedDept', 'IM2', 'IM3',
            'FCSEDIM1', 'FCSEDIM2', 'FCSEDIM3', 'DMCFOOC', 'POCnoa', 'DOC', 'Phyt', 'TPM', 'IM2S1',
            'IM3S1', 'IM2S2', 'IM3S2', 'Tau', 'TauShields', 'GRAIN50', 'GRAV', 'KinViscos',
            'RHOSAND', 'RhoWater', 'PORS2', 'ThickS2', 'MinDepth', 'MaxResPup', 'FactResPup',
            'SWResusp', 'ZResIM1', 'VResIM1', 'TaucRS1IM1', 'ZResIM2', 'VResIM2', 'TaucRS1IM2',
            'ZResIM3', 'VResIM3', 'TaucRS1IM3', 'DMS1', 'DMS2', 'fRIM1S2Pup', 'fRIM2S2Pup',
            'fRIM3S2Pup', 'fRTIMS2Pup', 'Pshields', 'FrTIMS2', 'FrPOMS2', 'fResS1IM1', 'fResS1IM2',
            'fResS1IM3', 'fResS1DM', 'fResS2DM', 'dResS1IM2', 'FrIM1S1', 'FrIM1S2', 'FrIM1S3',
            'fBurS1DM', 'fBurS2DM', 'fDigS1DM', 'fDigS2DM', 'SWDigS1', 'ZSedIM1', 'VSedIM1',
            'TaucSIM1', 'FrIM1SedS2', 'fSedIM1', 'fAtmDepIM1', 'sw1AtmDIM1', 'sw2AtmDIM1',
            'fDfwastIM1', 'sw1DfwaIM1', 'sw2DfwaIM1', 'ExtVl', 'PAConstant', 'SecchiDept',
            'basin_no', 'no_basin', 'ActThS1', 'ActThS2', 'start_dr01', 'start_dr02', 'start_dr03',
            'start_dr04', 'start_dr05', 'start_dr06', 'start_dr07', 'start_dr08', 'start_dr09',
            'freq__dr01', 'freq__dr02', 'freq__dr03', 'freq__dr04', 'freq__dr05', 'freq__dr06',
            'freq__dr07', 'freq__dr08', 'freq__dr09', 'crit__dr01', 'crit__dr02', 'crit__dr03',
            'crit__dr04', 'crit__dr05', 'crit__dr06', 'crit__dr07', 'crit__dr08', 'crit__dr09',
            'sws1s2dr01', 'sws1s2dr02', 'sws1s2dr03', 'sws1s2dr04', 'sws1s2dr05', 'sws1s2dr06',
            'sws1s2dr07', 'sws1s2dr08', 'sws1s2dr09', 'seg___dr01', 'seg___dr02', 'seg___dr03',
            'seg___dr04', 'seg___dr05', 'seg___dr06', 'seg___dr07', 'seg___dr08', 'seg___dr09',
            'speed_dr01', 'speed_dr02', 'speed_dr03', 'speed_dr04', 'speed_dr05', 'speed_dr06',
            'speed_dr07', 'speed_dr08', 'speed_dr09', 'relab_dr01', 'relab_dr02', 'relab_dr03',
            'relab_dr04', 'relab_dr05', 'relab_dr06', 'relab_dr07', 'relab_dr08', 'relab_dr09',
            'SwFloceq', 'RcFloc', 'RcBreakup', 'SPMratioem', 'VxRes0', 'VxSedDum', 'VxBur0',
            'VxTur0', 'VxDif0', 'VxSep0', 'FCSEDIM1S1', 'FCSEDIM2S1', 'FCSEDIM3S1', 'DMCFOOCS',
            'POCS1', 'dDumS1Mak', 'OOCS1', 'DetCS1', 'AAPS1', 'DetNS1', 'DetPS1', 'DetSiS1',
            'OONS1', 'PHYTS1', 'fSedIM2', 'fSedIM3', 'fSedPOCnoa', 'fSedPHYT', 'fAtmDepCd',
            'sw1AtmDCd', 'sw2AtmDCd', 'dAtmDepCd', 'fDfwastCd', 'sw1DfwaCd', 'sw2DfwaCd', 'QCrIM1',
            'QCrIM2', 'QCrIM3', 'QCrPOC', 'QCrPHYT', 'QCrDMS1', 'QCrDMS2', 'QCrDMS3', 'fAtmDepCr',
            'sw1AtmDCr', 'sw2AtmDCr', 'fDfwastCr', 'sw1DfwaCr', 'sw2DfwaCr', 'QCuIM1', 'QCuIM2',
            'QCuIM3', 'QCuPOC', 'QCuPHYT', 'fAtmDepCu', 'sw1AtmDCu', 'sw2AtmDCu', 'fDfwastCu',
            'sw1DfwaCu', 'sw2DfwaCu', 'fAtmDepNi', 'sw1AtmDNi', 'sw2AtmDNi', 'fDfwastNi',
            'sw1DfwaNi', 'sw2DfwaNi', 'QPbIM1', 'QPbIM2', 'QPbIM3', 'QPbPOC', 'QPbPHYT', 'QPbDMS1',
            'QPbDMS2', 'QPbDMS3', 'fAtmDepPb', 'sw1AtmDPb', 'sw2AtmDPb', 'fDfwastPb', 'sw1DfwaPb',
            'sw2DfwaPb', 'fAtmDepZn', 'sw1AtmDZn', 'sw2AtmDZn', 'fDfwastZn', 'sw1DfwaZn',
            'sw2DfwaZn', 'LocalDepth', 'Rad_1', 'VWind_1', 'WinDir_1', 'RelHum_1', 'AirTemp_1',
            'AirPres_1', 'Cloud_1', 'Rad_2', 'VWind_2', 'WinDir_2', 'RelHum_2', 'AirTemp_2',
            'AirPres_2', 'Cloud_2', 'Rad_3', 'VWind_3', 'WinDir_3', 'RelHum_3', 'AirTemp_3',
            'AirPres_3', 'Cloud_3', 'Rad_4', 'VWind_4', 'WinDir_4', 'RelHum_4', 'AirTemp_4',
            'AirPres_4', 'Cloud_4', 'Rad_5', 'VWind_5', 'WinDir_5', 'RelHum_5', 'AirTemp_5',
            'AirPres_5', 'Cloud_5', 'Rad_6', 'VWind_6', 'WinDir_6', 'RelHum_6', 'AirTemp_6',
            'AirPres_6', 'Cloud_6', 'Rad_7', 'VWind_7', 'WinDir_7', 'RelHum_7', 'AirTemp_7',
            'AirPres_7', 'Cloud_7', 'Rad_8', 'VWind_8', 'WinDir_8', 'RelHum_8', 'AirTemp_8',
            'AirPres_8', 'Cloud_8', 'Rad_9', 'VWind_9', 'WinDir_9', 'RelHum_9', 'AirTemp_9',
            'AirPres_9', 'Cloud_9', 'Rad_10', 'VWind_10', 'WinDir_10', 'RelHum_10', 'AirTemp_10',
            'AirPres_10', 'Cloud_10', 'XMeteo1', 'YMeteo1', 'XMeteo2', 'YMeteo2', 'XMeteo3',
            'YMeteo3', 'XMeteo4', 'YMeteo4', 'XMeteo5', 'YMeteo5', 'XMeteo6', 'YMeteo6', 'XMeteo7',
            'YMeteo7', 'XMeteo8', 'YMeteo8', 'XMeteo9', 'YMeteo9', 'XMeteo10', 'YMeteo10',
            'XYScaleFac', 'NoMeteoSta', 'MeteoClcSW', 'XSeg', 'YSeg', 'RadSW', 'WinDir',
            'RelHumAir', 'TempAir', 'PAtm', 'Cloud', 'XDOCCd', 'KdCdIM1', 'KdCdIM2', 'DOCS1',
            'KdCdIM1S1', 'KdCdIM2S1', 'XDOCCr', 'KdCrIM1', 'KdCrIM2', 'KdCrIM1S1', 'KdCrIM2S1',
            'XDOCCu', 'KdCuIM1', 'KdCuIM2', 'XDOCPb', 'KdPbIM1', 'KdPbIM2', 'KdPbIM1S1',
            'KdPbIM2S1', 'XDOCZn', 'KdZnIM1', 'KdZnIM2'
        ),
    ),
    'coliform': _model(
        key='coliform', ui_key='Coliform',
        title='E. coli bacteria',
        b1_file='B1_coliform.inc',
        substances=('Salinity', 'EColi'),
        processes=('EColiMrt', 'Salinchlor', 'CalcRadDay', 'DynDepth'),
        constants={
            'RcMrtEColi': '0.8', 'DayL': '0.58', 'ExtVl': '1', 'DayRadSurf': '-999',
        },
        segfunctions=(('Temp', 'tem_path'),),
    ),
}

# Lookup by either key style
_BY_UI_KEY = {m.ui_key: m for m in MODELS.values()}

def get_model(key: str) -> WaqModel:
    """Return the model for an internal key ("simple-oxygen") or a frontend key ("Simple_Oxygen")."""
    model = MODELS.get(key) or _BY_UI_KEY.get(key)
    if model is None:
        known = ", ".join(f"{m.ui_key} ({m.key})" for m in MODELS.values())
        raise KeyError(f"Unknown water quality model {key!r}. Known models: {known}")
    return model