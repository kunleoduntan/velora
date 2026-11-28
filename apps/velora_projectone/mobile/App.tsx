import React, { useEffect, useState } from 'react';
import { ActivityIndicator, Alert, Appearance, FlatList, Pressable, RefreshControl, SafeAreaView, ScrollView, StatusBar, StyleSheet, Text, TextInput, View } from 'react-native';
import * as SecureStore from 'expo-secure-store';
import { clearAccessToken, getAccessToken, routes, setUnauthorizedHandler } from './src/api';
import { login, logout, restoreSession, selectCompany, VeloraProfile } from './src/auth';

type Tab = 'Home' | 'Projects' | 'Approvals' | 'Timesheets' | 'More';
type ThemeMode = 'light' | 'dark' | 'system';
type ThemePreset = 'classic' | 'ocean' | 'midnight' | 'emerald' | 'rose';
const THEME_STORAGE_KEY = 'velora.projectone.mobile.theme.v1';
const THEME_PRESET_STORAGE_KEY = 'velora.projectone.mobile.theme-preset.v1';
const THEME_PRESETS: Record<ThemePreset, {name:string; description:string; light:any; dark:any}> = {
  classic: { name:'Velora Classic', description:'Signature navy, blue and pink identity', light:{navy:'#102A43',blue:'#1769AA',pink:'#E84A8A',accentBg:'#EAF3FB',glyphBg:'#EAF3FB'}, dark:{navy:'#0B1928',blue:'#78B9F2',pink:'#F078AB',accentBg:'#20384E',glyphBg:'#20384E'} },
  ocean: { name:'Ocean Blue', description:'Cool blue with a fresh cyan highlight', light:{navy:'#10334A',blue:'#087EAB',pink:'#16A6B8',accentBg:'#E5F5FA',glyphBg:'#E5F5FA'}, dark:{navy:'#0B2434',blue:'#63C8E8',pink:'#65D5D0',accentBg:'#173A4B',glyphBg:'#173A4B'} },
  midnight: { name:'Executive Midnight', description:'Deep indigo with refined violet accents', light:{navy:'#25264A',blue:'#5B5FC7',pink:'#9878E8',accentBg:'#F0EEFC',glyphBg:'#F0EEFC'}, dark:{navy:'#17182F',blue:'#AAA5FF',pink:'#C2A5FF',accentBg:'#302F50',glyphBg:'#302F50'} },
  emerald: { name:'Emerald', description:'Confident forest green and teal', light:{navy:'#153D35',blue:'#16765C',pink:'#24A68A',accentBg:'#E8F5F0',glyphBg:'#E8F5F0'}, dark:{navy:'#0D2924',blue:'#65CBA9',pink:'#73DCC0',accentBg:'#1C4038',glyphBg:'#1C4038'} },
  rose: { name:'Rose', description:'Warm berry with a soft rose accent', light:{navy:'#49263B',blue:'#A33C70',pink:'#D45A8C',accentBg:'#F9EAF1',glyphBg:'#F9EAF1'}, dark:{navy:'#301A29',blue:'#E58AB5',pink:'#F1A0C4',accentBg:'#4A293C',glyphBg:'#4A293C'} },
};
const PALETTES: Record<'light' | 'dark', any> = {
  light: { navy:'#102A43', blue:'#1769AA', pink:'#E84A8A', buttonText:'#FFFFFF', bg:'#F3F6FA', card:'#FFFFFF', text:'#182B3A', muted:'#687B8C', line:'#E3EAF0', green:'#16845B', amber:'#B7791F', red:'#B93838', heading:'#102A43', buttonSecondaryText:'#102A43', border:'#E7EDF3', secondary:'#EAF1F7', tabInactive:'#8292A1', inputBg:'#FBFCFE', searchBg:'#FFFFFF', accentBg:'#EAF3FB', statusBg:'#F0F4F8', statusText:'#52687A', liveBg:'#E4F5ED', weekBg:'#EEF5FB', glyphBg:'#EAF3FB' },
  dark: { navy:'#0B1928', blue:'#78B9F2', pink:'#F078AB', buttonText:'#102131', bg:'#0D1722', card:'#162536', text:'#E7EEF5', muted:'#A3B2C2', line:'#2B3D50', green:'#69D6A2', amber:'#F3C36A', red:'#FF8585', heading:'#E7EEF5', buttonSecondaryText:'#E7EEF5', border:'#293C50', secondary:'#23374B', tabInactive:'#8FA2B5', inputBg:'#102131', searchBg:'#102131', accentBg:'#20384E', statusBg:'#23374B', statusText:'#C3D1DE', liveBg:'#183B31', weekBg:'#1B344B', glyphBg:'#20384E' },
};
let C: any = PALETTES.light;
let s: any;

function Button({ title, onPress, secondary=false, disabled=false }: any) { return <Pressable onPress={onPress} disabled={disabled} accessibilityRole="button" accessibilityState={{disabled}} style={({pressed})=>[s.button, secondary && s.secondary, disabled && s.disabled, pressed && !disabled && s.buttonPressed]}><Text style={[s.buttonText, secondary && {color:C.buttonSecondaryText}]}>{title}</Text></Pressable>; }
function Card({ children }: any) { return <View style={s.card}>{children}</View>; }
function Heading({ children }: any) { return <Text accessibilityRole="header" style={s.heading}>{children}</Text>; }
function Metric({ label, value, tone=C.blue }: any) { return <View style={s.metric}><View style={[s.metricAccent,{backgroundColor:tone}]}/><Text style={[s.metricValue,{color:tone}]}>{value ?? '—'}</Text><Text style={s.metricLabel}>{label.replace(/_/g,' ')}</Text></View>; }
function Empty({ text }: {text:string}) { return <Card><Text style={s.muted}>{text}</Text></Card>; }

export default function App() {
  const [token, setToken] = useState<string|null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [tab, setTab] = useState<Tab>('Home');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [profile, setProfile] = useState<VeloraProfile|null>(null);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [totpCode, setTotpCode] = useState('');
  const [themeMode, setThemeMode] = useState<ThemeMode>('system');
  const [themePreset, setThemePreset] = useState<ThemePreset>('classic');
  const [systemScheme, setSystemScheme] = useState(Appearance.getColorScheme() || 'light');
  const [, setThemeRevision] = useState(0);
  const resolvedTheme: 'light' | 'dark' = themeMode === 'system' ? (systemScheme === 'dark' ? 'dark' : 'light') : themeMode;

  useEffect(() => {
    SecureStore.getItemAsync(THEME_STORAGE_KEY).then(value => {
      if (value === 'light' || value === 'dark' || value === 'system') setThemeMode(value);
    }).catch(() => undefined);
    SecureStore.getItemAsync(THEME_PRESET_STORAGE_KEY).then(value => {
      if (value && Object.prototype.hasOwnProperty.call(THEME_PRESETS, value)) setThemePreset(value as ThemePreset);
    }).catch(() => undefined);
    const subscription = Appearance.addChangeListener(({ colorScheme }) => setSystemScheme(colorScheme || 'light'));
    return () => subscription.remove();
  }, []);
  useEffect(() => {
    C = { ...PALETTES[resolvedTheme], ...THEME_PRESETS[themePreset][resolvedTheme] };
    s = createStyles(C);
    setThemeRevision(value => value + 1);
  }, [resolvedTheme, themePreset]);
  const changeTheme = async (mode: ThemeMode) => {
    setThemeMode(mode);
    try { await SecureStore.setItemAsync(THEME_STORAGE_KEY, mode); }
    catch { Alert.alert('Theme preference', 'Your appearance mode changed for this session, but could not be saved on this device.'); }
  };
  const changeThemePreset = async (preset: ThemePreset) => {
    setThemePreset(preset);
    try { await SecureStore.setItemAsync(THEME_PRESET_STORAGE_KEY, preset); }
    catch { Alert.alert('Theme preference', 'Your colour theme changed for this session, but could not be saved on this device.'); }
  };

  useEffect(() => {
    let mounted = true;
    const restore = async () => {
      try {
        const saved = await getAccessToken();
        if (saved) {
          let current = await restoreSession();
          const target = current.active_company || current.default_company || (current.companies.length === 1 ? current.companies[0].id : null);
          if (target && !current.active_company) {
            await selectCompany(target);
            current = { ...current, active_company: target };
          }
          if (mounted) { setProfile(current); setToken(saved); }
        }
      } catch { await clearAccessToken(); }
      finally { if (mounted) setAuthReady(true); }
    };
    restore();
    setUnauthorizedHandler(() => { setToken(null); setProfile(null); setTab('Home'); });
    return () => { mounted = false; setUnauthorizedHandler(null); };
  }, []);

  const signIn = async () => {
    setError('');
    if (!email.trim() || !password) { setError('Enter your Velora email address and password.'); return; }
    setBusy(true);
    try {
      let current = await login(email, password, totpCode);
      const target = current.active_company || current.default_company || (current.companies.length === 1 ? current.companies[0].id : null);
      if (target && !current.active_company) {
        await selectCompany(target);
        current = { ...current, active_company: target };
      }
      setProfile(current);
      setToken(await getAccessToken());
      setPassword('');
      setTotpCode('');
    } catch (e:any) { setError(e.message || 'Velora sign-in failed.'); }
    finally { setBusy(false); }
  };
  const chooseCompany = async (companyId:string) => {
    setBusy(true); setError('');
    try {
      await selectCompany(companyId);
      setProfile(current => current ? { ...current, active_company: companyId } : current);
    } catch (e:any) { setError(e.message || 'Unable to switch company.'); }
    finally { setBusy(false); }
  };
  const signOut = async () => {
    try { await logout(); } catch { await clearAccessToken(); }
    setToken(null); setProfile(null); setPassword(''); setTotpCode(''); setTab('Home');
  };

  if (!authReady) return <SafeAreaView style={s.safe}><StatusBar barStyle="light-content" backgroundColor={C.navy}/><View style={s.authLoading}><ActivityIndicator color="#FFFFFF" size="large"/><Text style={s.footer}>Preparing your secure workspace…</Text></View></SafeAreaView>;
  if (!token) return <SafeAreaView style={s.safe}><StatusBar barStyle="light-content" backgroundColor={C.navy}/><ScrollView contentContainerStyle={[s.login,{flexGrow:1}]} keyboardShouldPersistTaps="handled"><View style={s.logo}><Text style={s.logoText}>P</Text></View><Text style={s.brand}>Velora ProjectOne</Text><Text style={s.tagline}>Enterprise Project & Portfolio Management</Text><Card><Heading>Sign in to Velora</Heading><Text style={s.body}>Use your existing Velora account. The same password policy, account lockout, session controls and optional authenticator verification apply.</Text><Text style={s.label}>Email address</Text><TextInput style={s.input} autoCapitalize="none" autoComplete="email" keyboardType="email-address" textContentType="username" value={email} onChangeText={setEmail} placeholder="name@company.com" placeholderTextColor={C.muted}/><Text style={s.label}>Password</Text><TextInput style={s.input} secureTextEntry autoComplete="password" textContentType="password" value={password} onChangeText={setPassword} placeholder="Your Velora password" placeholderTextColor={C.muted}/><Text style={s.label}>Authenticator code (if enabled)</Text><TextInput style={s.input} keyboardType="number-pad" maxLength={6} value={totpCode} onChangeText={setTotpCode} placeholder="6-digit code" placeholderTextColor={C.muted}/><Button title={busy ? 'Signing in…' : 'Sign in'} onPress={signIn} disabled={busy}/>{!!error && <Text style={s.error}>{error}</Text>}</Card><Text style={s.footer}>Mobile companion · v1.4.0 · Velora Framework 1.13.0</Text></ScrollView></SafeAreaView>;

  if (!profile || (!profile.active_company && profile.companies.length > 1)) return <SafeAreaView style={s.safe}><StatusBar barStyle="light-content" backgroundColor={C.navy}/><ScrollView contentContainerStyle={[s.login,{flexGrow:1}]}><View style={s.logo}><Text style={s.logoText}>P</Text></View><Text style={s.brand}>Choose your company</Text><Text style={s.tagline}>Your Velora account has access to more than one company.</Text><Card>{profile?.companies.map(company=><Pressable key={company.id} onPress={()=>chooseCompany(company.id)} style={s.themeOption}><View style={{flex:1,gap:3}}><Text style={s.themeOptionTitle}>{company.name}</Text><Text style={s.themeOptionDescription}>{company.tenant || company.id} · {company.status || 'status unavailable'}</Text></View><Text style={s.chevron}>›</Text></Pressable>)}<Button title={busy?'Selecting…':'Sign out'} secondary onPress={signOut}/>{!!error&&<Text style={s.error}>{error}</Text>}</Card></ScrollView></SafeAreaView>;
  if (!profile || profile.companies.length === 0) return <SafeAreaView style={s.safe}><View style={s.login}><Text style={s.brand}>No company access</Text><Text style={s.tagline}>Your Velora account is authenticated but has not been granted access to an active company. Contact your Velora administrator.</Text><Button title="Sign out" onPress={signOut}/></View></SafeAreaView>;

  return <SafeAreaView style={s.safe}><StatusBar barStyle="light-content" backgroundColor={C.navy}/><View style={s.header}><View style={s.headerBrand}><View style={s.headerMark}><Text style={s.headerMarkText}>P</Text></View><View><Text style={s.headerEyebrow}>VELORA WORKSPACE</Text><Text style={s.headerTitle}>ProjectOne</Text></View></View><View style={s.securePill}><View style={s.onlineDot}/><Text style={s.secureText}>Secure</Text></View></View><View style={s.content}>{tab==='Home' ? <HomeScreen/> : tab==='Projects' ? <ProjectsScreen/> : tab==='Approvals' ? <ApprovalsScreen/> : tab==='Timesheets' ? <TimesheetsScreen/> : <MoreScreen profile={profile} onChooseCompany={chooseCompany} onSignOut={signOut} themeMode={themeMode} onThemeChange={changeTheme} themePreset={themePreset} onThemePresetChange={changeThemePreset} resolvedTheme={resolvedTheme}/>}</View><View style={s.tabbar}>{(['Home','Projects','Approvals','Timesheets','More'] as Tab[]).map(t=><Pressable key={t} onPress={()=>setTab(t)} accessibilityRole="tab" accessibilityState={{selected:tab===t}} accessibilityLabel={`${t} tab`} hitSlop={6} style={s.tab}><View style={[s.tabIconWrap,tab===t&&s.tabIconActive]}><Text style={[s.tabIcon,tab===t&&{color:C.blue}]}>{({Home:'⌂',Projects:'▤',Approvals:'✓',Timesheets:'◷',More:'•••'} as any)[t]}</Text></View><Text style={[s.tabLabel,tab===t&&{color:C.blue,fontWeight:'800'}]}>{t}</Text></Pressable>)}</View></SafeAreaView>;
}

function useLoad<T>(loader:()=>Promise<T>, deps:any[] = []) {
  const [data,setData]=useState<T|null>(null); const [loading,setLoading]=useState(true); const [error,setError]=useState(''); const [refreshing,setRefreshing]=useState(false);
  const load=async(refresh=false)=>{refresh?setRefreshing(true):setLoading(true);setError('');try{setData(await loader());}catch(e:any){setError(e.message||'Unable to load data.');}finally{setLoading(false);setRefreshing(false);}};
  useEffect(()=>{load();},deps);
  return {data,loading,error,refresh:()=>load(true),refreshing};
}
function StateView({loading,error,refresh}:any){if(loading)return <View style={s.center}><ActivityIndicator color={C.blue}/><Text style={s.muted}>Loading authorised records…</Text></View>;if(error)return <Card><Text style={s.error}>{error}</Text><Button title="Retry" onPress={refresh} secondary/></Card>;return null;}
function HomeScreen(){const q=useLoad<any>(()=>routes.executive(),[]);const d=q.data||{};const money=(v:any)=>Number(v||0).toLocaleString(undefined,{maximumFractionDigits:0});const fin=(d.financial_by_currency||[])[0];const summary:any={...(fin?{[`Budget ${fin.currency}`]:money(fin.approved_budget),[`Actual cost ${fin.currency}`]:money(fin.actual_cost),[`Revenue ${fin.currency}`]:money(fin.recognised_revenue)}:{}),'Data issues':String(d.data_quality?.issue_count??0),'Sources connected':`${d.source_health?.connected_count??0} of ${d.source_health?.source_count??0}`};return <ScrollView showsVerticalScrollIndicator={false} refreshControl={<RefreshControl tintColor={C.blue} refreshing={q.refreshing} onRefresh={q.refresh}/>} contentContainerStyle={s.scroll}><View style={s.welcome}><Text style={s.welcomeEyebrow}>YOUR DELIVERY AT A GLANCE</Text><Text style={s.welcomeTitle}>Good to see you</Text><Text style={s.welcomeCopy}>A clear view of the work that moves your organisation forward.</Text><View style={s.welcomeTag}><View style={s.welcomeDot}/><Text style={s.welcomeTagText}>Portfolio workspace</Text></View></View><View style={s.sectionHead}><View><Text style={s.eyebrow}>EXECUTIVE OVERVIEW</Text><Heading>Portfolio snapshot</Heading></View><Text style={s.liveLabel}>LIVE DATA</Text></View><StateView {...q}/>{q.data&&<><View style={s.metrics}>{Object.entries(summary).slice(0,4).map(([k,v]:any)=><Metric key={k} label={k} value={typeof v==='object'?v.value??'—':String(v)}/>)}</View><Heading>Portfolio position</Heading><Card><Text style={s.body}>This dashboard displays the executive workspace returned by Velora. Financial values remain separated by currency and governed by your source permissions.</Text><Text style={s.small}>Read-only management view · Pull down to refresh authorised information</Text></Card></>}</ScrollView>}
function TaskCard({task}:any){const [note,setNote]=useState('');const [saving,setSaving]=useState(false);const [status,setStatus]=useState('');const submit=async()=>{if(!note.trim())return setStatus('Enter a note first.');setSaving(true);setStatus('');try{await routes.comment(task.name,note.trim());setNote('');setStatus('Note recorded in the project activity audit.');}catch(e:any){setStatus(e.message);}finally{setSaving(false);}};return <Card><Text style={s.cardTitle}>{task.title||task.subject||task.name}</Text><Text style={s.muted}>{task.priority||'Normal'} · {task.assignee||'Unassigned'} · Due {task.planned_finish||'not set'}</Text><TextInput style={[s.input,{minHeight:64,textAlignVertical:'top'}]} multiline maxLength={4000} placeholder="Add an append-only project note" value={note} onChangeText={setNote}/><Button title={saving?'Recording…':'Add project note'} onPress={submit} disabled={saving}/>{!!status&&<Text style={status.includes('recorded')?{color:C.green,fontSize:12}:{color:C.red,fontSize:12}}>{status}</Text>}</Card>;}
function ProjectsScreen(){const q=useLoad<any>(()=>routes.projects(),[]);const [search,setSearch]=useState('');const [selected,setSelected]=useState<any>(null);const [work,setWork]=useState<any>(null);const [workError,setWorkError]=useState('');const [loadingWork,setLoadingWork]=useState(false);const projects=(q.data||[]).filter((p:any)=>`${p.project_name||p.title||p.name} ${p.name} ${p.status||''}`.toLowerCase().includes(search.toLowerCase()));const open=async(p:any)=>{setSelected(p);setWork(null);setWorkError('');setLoadingWork(true);try{setWork(await routes.workbench(p.name));}catch(e:any){setWorkError(e.message);}finally{setLoadingWork(false);}};return <View style={{flex:1}}>{selected?<ScrollView contentContainerStyle={s.scroll}><Button title="← All projects" secondary onPress={()=>setSelected(null)}/><Heading>{selected.project_name||selected.title||selected.name}</Heading><Text style={s.muted}>{selected.name} · {selected.status||'Status not supplied'}</Text>{loadingWork?<ActivityIndicator color={C.blue}/>:workError?<Text style={s.error}>{workError}</Text>:work&&<><View style={s.metrics}>{Object.entries(work.counts||{}).slice(0,4).map(([k,v]:any)=><Metric key={k} label={k.replace(/_/g,' ')} value={String(v)}/>)}</View><Heading>Action centre</Heading>{Object.entries(work.action_centre||{}).map(([k,rows]:any)=><Card key={k}><Text style={s.cardTitle}>{k.replace(/_/g,' ')}</Text>{rows.length?rows.map((r:any)=><Text key={r.name} style={s.listLine}>{r.title||r.task_code||r.name} · {r.assignee||'Unassigned'}</Text>):<Text style={s.muted}>No items</Text>}</Card>)}<Heading>Project task lanes</Heading>{Object.entries(work.lanes||{}).map(([lane,rows]:any)=><View key={lane} style={{gap:8}}><Text style={s.cardTitle}>{lane} ({rows.length})</Text>{rows.map((task:any)=><TaskCard key={task.name} task={task}/>)}</View>)}<Text style={s.small}>Task dates and status are governed by server-side schedule and workflow controls. Notes are append-only and cannot be edited here.</Text></>}</ScrollView>:<FlatList data={projects} keyExtractor={(p:any)=>p.name} contentContainerStyle={s.scroll} refreshControl={<RefreshControl refreshing={q.refreshing} onRefresh={q.refresh}/>} ListHeaderComponent={<><Text style={s.eyebrow}>DELIVERY PORTFOLIO</Text><Heading>Projects</Heading><Text style={s.muted}>Find a project and open its execution workbench.</Text><TextInput accessibilityLabel="Search projects" style={s.searchInput} placeholder="Search by project or status" placeholderTextColor={C.muted} value={search} onChangeText={setSearch}/><StateView {...q}/></>} renderItem={({item}:any)=><Pressable onPress={()=>open(item)} accessibilityRole="button" accessibilityLabel={`Open project ${item.project_name||item.title||item.name}`}><Card><View style={s.projectCardTop}><View style={s.projectGlyph}><Text style={s.projectGlyphText}>▤</Text></View><View style={{flex:1}}><Text style={s.cardTitle}>{item.project_name||item.title||item.name}</Text><Text style={s.muted}>{item.name}</Text></View><Text style={s.chevron}>›</Text></View><View style={s.statusPill}><Text style={s.statusPillText}>{item.status||'Status unavailable'}</Text></View></Card></Pressable>} ListEmptyComponent={!q.loading&&!q.error?<Empty text="No projects were returned for your account."/>:null}/> }</View>}
function ApprovalsScreen(){const q=useLoad<any>(()=>routes.approvals(),[]);const items=q.data||[];const [busy,setBusy]=useState('');const act=async(item:any,action:string)=>{const doctype=item.doctype||item.reference_doctype;if(!doctype||!item.name){Alert.alert('Approval unavailable','The workflow item is missing its document reference. Refresh the inbox or contact your administrator.');return;}Alert.alert(`${action} approval?`,'The host workflow will validate whether this action is permitted.',[{text:'Cancel',style:'cancel'},{text:'Continue',onPress:async()=>{setBusy(item.name);try{await routes.workflow(doctype,item.name,action);q.refresh();}catch(e:any){Alert.alert('Workflow action not completed',e.message);}finally{setBusy('');}}}]);};return <ScrollView contentContainerStyle={s.scroll} refreshControl={<RefreshControl refreshing={q.refreshing} onRefresh={q.refresh}/>}><Text style={s.eyebrow}>GOVERNED WORKFLOW</Text><Heading>My approvals</Heading><Text style={s.muted}>Pending items returned by the Velora workflow provider.</Text><StateView {...q}/>{items.map((x:any)=><Card key={x.name}><Text style={s.cardTitle}>{x.title||x.subject||x.name}</Text><Text style={s.muted}>{x.doctype||x.reference_doctype||'Workflow item'} · {x.status||'Pending'}</Text><View style={s.row}><Button title={busy===x.name?'Working…':'Approve'} onPress={()=>act(x,'approve')} disabled={!!busy}/><Button title="Reject" secondary onPress={()=>act(x,'reject')} disabled={!!busy}/></View></Card>)}{q.data&&items.length===0&&<Empty text="There are no pending approvals, or the host workflow adapter returned no items."/>}</ScrollView>}
function TimesheetsScreen(){const [hours,setHours]=useState('8');const [days,setDays]=useState('5');const h=Number(hours),d=Number(days);const valid=hours.trim()!==''&&days.trim()!==''&&Number.isFinite(h)&&Number.isFinite(d)&&h>=0&&h<=24&&d>=0&&d<=7;const total=valid?h*d:0;return <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={s.scroll}><Text style={s.eyebrow}>TIME & EFFORT</Text><Heading>Timesheet helper</Heading><Text style={s.muted}>Prepare a weekly hours check before submitting through your organisation’s approved timesheet process.</Text><Card><Text style={s.label}>Hours per working day</Text><TextInput accessibilityLabel="Hours per working day" style={s.input} keyboardType="decimal-pad" value={hours} onChangeText={setHours} maxLength={5}/><Text style={s.label}>Working days per week</Text><TextInput accessibilityLabel="Working days per week" style={s.input} keyboardType="number-pad" value={days} onChangeText={setDays} maxLength={1}/>{!valid&&<Text style={s.error}>Enter hours from 0 to 24 and working days from 0 to 7.</Text>}<View style={s.weekTotal}><Text style={s.weekTotalLabel}>ESTIMATED WEEKLY HOURS</Text><Text style={s.weekTotalValue}>{valid?total.toFixed(1):'—'}</Text><Text style={s.small}>Based on the values entered above</Text></View><Text style={s.small}>Planning aid only. This screen does not create, submit or approve timesheets. Actual time records and any HRMS hand-off remain governed by the server workflow.</Text></Card></ScrollView>}
function MoreScreen({profile,onChooseCompany,onSignOut,themeMode,onThemeChange,themePreset,onThemePresetChange,resolvedTheme}:any){const q=useLoad<any>(()=>routes.integration(),[]);const choices:[ThemeMode,string,string][]=[['light','Light','Bright, clean workspace'],['dark','Dark','Comfortable low-light palette'],['system','System','Follow your device appearance']];return <ScrollView contentContainerStyle={s.scroll}><Text style={s.eyebrow}>ACCOUNT & SYSTEM</Text><Heading>More</Heading><Card><Text style={s.cardTitle}>Signed in account</Text><Text style={s.body}>{profile?.user?.full_name || profile?.user?.email}</Text><Text style={s.muted}>{profile?.user?.email}</Text><Text style={s.label}>Active company</Text>{profile?.companies?.map((company:any)=><Pressable key={company.id} accessibilityRole="button" accessibilityState={{selected:profile.active_company===company.id}} onPress={()=>onChooseCompany(company.id)} style={[s.themeOption,profile.active_company===company.id&&s.themeOptionActive]}><View style={{flex:1,gap:3}}><Text style={s.themeOptionTitle}>{company.name}</Text><Text style={s.themeOptionDescription}>{(company.roles||[]).join(' · ') || 'No role details returned'}</Text></View><Text style={s.chevron}>{profile.active_company===company.id?'✓':'›'}</Text></Pressable>)}</Card><Card><Text style={s.cardTitle}>Appearance mode</Text><Text style={s.muted}>Choose light, dark or automatic device appearance.</Text>{choices.map(([mode,title,description])=><Pressable key={mode} accessibilityRole="radio" accessibilityState={{selected:themeMode===mode}} onPress={()=>onThemeChange(mode)} style={[s.themeOption,themeMode===mode&&s.themeOptionActive]}><View style={{flex:1,gap:3}}><Text style={s.themeOptionTitle}>{title}</Text><Text style={s.themeOptionDescription}>{description}</Text></View><View style={[s.themeRadio,themeMode===mode&&s.themeRadioActive]}>{themeMode===mode&&<View style={s.themeRadioDot}/>}</View></Pressable>)}</Card><Card><Text style={s.cardTitle}>Colour themes</Text><Text style={s.muted}>Select a brand palette. Your choice is saved on this device and works with all three appearance modes.</Text>{(Object.keys(THEME_PRESETS) as ThemePreset[]).map(key=>{const item=THEME_PRESETS[key];const active=themePreset===key;return <Pressable key={key} accessibilityRole="radio" accessibilityLabel={`${item.name} colour theme`} accessibilityState={{selected:active}} onPress={()=>onThemePresetChange(key)} style={[s.themeOption,active&&s.themeOptionActive]}><View style={s.swatchRow}><View style={[s.swatch,{backgroundColor:(item as any)[resolvedTheme].navy}]}/><View style={[s.swatch,{backgroundColor:(item as any)[resolvedTheme].blue}]}/><View style={[s.swatch,{backgroundColor:(item as any)[resolvedTheme].pink}]}/></View><View style={{flex:1,gap:3}}><Text style={s.themeOptionTitle}>{item.name}</Text><Text style={s.themeOptionDescription}>{item.description}</Text></View><View style={[s.themeRadio,active&&s.themeRadioActive]}>{active&&<View style={s.themeRadioDot}/>}</View></Pressable>})}</Card><Card><Text style={s.cardTitle}>Integration readiness</Text><StateView {...q}/>{q.data&&<><Text style={s.body}>Native integration: {q.data.native?.status||'Status not reported'}</Text><Text style={s.small}>A configured connection is not proof of live source reconciliation or production qualification.</Text></>}</Card><Card><Text style={s.cardTitle}>About ProjectOne Mobile</Text><Text style={s.body}>Mobile app 1.4.0 · ProjectOne server baseline 2.15.0</Text><Text style={s.small}>Authentication uses Velora’s existing password and optional TOTP services. Opaque Velora session tokens are stored in device secure storage and can be revoked by server logout or administrator session controls. Company membership and permissions are checked by Velora.</Text></Card><Button title="Sign out" secondary onPress={onSignOut}/></ScrollView>}

const createStyles=(C:any)=>StyleSheet.create({
  safe:{flex:1,backgroundColor:C.bg},
  authLoading:{flex:1,backgroundColor:C.navy,alignItems:'center',justifyContent:'center',gap:14},
  header:{backgroundColor:C.navy,paddingHorizontal:18,paddingVertical:14,flexDirection:'row',justifyContent:'space-between',alignItems:'center'},
  headerBrand:{flexDirection:'row',alignItems:'center',gap:11},
  headerMark:{width:42,height:42,borderRadius:14,backgroundColor:C.pink,alignItems:'center',justifyContent:'center',shadowColor:'#000',shadowOpacity:.15,shadowRadius:8,elevation:3},
  headerMarkText:{color:'#FFF',fontWeight:'900',fontSize:24},
  headerEyebrow:{fontSize:9,color:'#A9C3D8',letterSpacing:1.8,fontWeight:'900'},
  headerTitle:{fontSize:21,color:'#FFF',fontWeight:'900',letterSpacing:-.4},
  securePill:{flexDirection:'row',alignItems:'center',gap:6,borderRadius:20,paddingHorizontal:10,paddingVertical:6,backgroundColor:'#1D405A'},
  onlineDot:{width:6,height:6,borderRadius:3,backgroundColor:'#69D6A2'},secureText:{fontSize:10,color:'#D7E6F0',fontWeight:'800'},
  avatar:{width:38,height:38,borderRadius:19,backgroundColor:C.pink,alignItems:'center',justifyContent:'center'},avatarText:{color:'#FFF',fontWeight:'900'},
  content:{flex:1},scroll:{padding:16,paddingBottom:30,gap:13},
  welcome:{backgroundColor:C.navy,borderRadius:20,padding:19,gap:7,overflow:'hidden'},welcomeEyebrow:{fontSize:9,color:'#B5CDE0',letterSpacing:1.7,fontWeight:'900'},welcomeTitle:{fontSize:26,color:'#FFF',fontWeight:'900',letterSpacing:-.7},welcomeCopy:{fontSize:13,color:'#D1DFE9',lineHeight:19,maxWidth:290},welcomeTag:{marginTop:8,alignSelf:'flex-start',backgroundColor:'#244B68',borderRadius:20,paddingHorizontal:10,paddingVertical:7,flexDirection:'row',alignItems:'center',gap:7},welcomeDot:{width:6,height:6,borderRadius:3,backgroundColor:'#F18AB4'},welcomeTagText:{fontSize:10,color:'#F5F8FB',fontWeight:'800'},
  sectionHead:{flexDirection:'row',alignItems:'flex-end',justifyContent:'space-between'},liveLabel:{fontSize:9,color:C.green,fontWeight:'900',letterSpacing:1,backgroundColor:C.liveBg,paddingHorizontal:9,paddingVertical:6,borderRadius:20,overflow:'hidden'},
  eyebrow:{color:C.blue,fontSize:10,letterSpacing:1.5,fontWeight:'900'},heading:{fontSize:20,color:C.heading,fontWeight:'900',marginTop:3,letterSpacing:-.3},muted:{color:C.muted,fontSize:13,lineHeight:19},body:{color:C.text,fontSize:14,lineHeight:21,marginVertical:8},small:{fontSize:11,color:C.muted,lineHeight:16,marginTop:7},
  card:{backgroundColor:C.card,borderRadius:17,padding:15,borderWidth:1,borderColor:C.border,gap:9,shadowColor:'#15324A',shadowOpacity:.045,shadowRadius:10,shadowOffset:{width:0,height:3},elevation:1},cardTitle:{fontSize:14,fontWeight:'900',color:C.navy,letterSpacing:-.1},
  metrics:{flexDirection:'row',flexWrap:'wrap',gap:10},metric:{backgroundColor:C.card,borderColor:C.border,borderWidth:1,borderRadius:16,padding:13,minWidth:'47%',flexGrow:1,overflow:'hidden'},metricAccent:{width:24,height:4,borderRadius:3,marginBottom:8},metricValue:{fontSize:24,fontWeight:'900',letterSpacing:-.5},metricLabel:{fontSize:10,color:C.muted,textTransform:'capitalize',marginTop:4,fontWeight:'700'},
  button:{backgroundColor:C.blue,borderRadius:12,paddingVertical:13,paddingHorizontal:16,alignItems:'center',justifyContent:'center',marginTop:5,minHeight:44},secondary:{backgroundColor:C.secondary},disabled:{opacity:.45},buttonPressed:{opacity:.82,transform:[{scale:.99}]},buttonText:{color:C.buttonText||'#FFF',fontWeight:'900',fontSize:13},
  error:{color:C.red,fontSize:12,lineHeight:18,marginTop:8},center:{padding:28,alignItems:'center',gap:10},
  tabbar:{height:72,backgroundColor:C.card,borderTopWidth:1,borderColor:C.line,flexDirection:'row',justifyContent:'space-around',alignItems:'center',paddingBottom:5},tab:{alignItems:'center',justifyContent:'center',flex:1,gap:3,minHeight:58},tabIconWrap:{width:38,height:29,borderRadius:11,alignItems:'center',justifyContent:'center'},tabIconActive:{backgroundColor:C.glyphBg},tabIcon:{fontSize:19,color:C.tabInactive,fontWeight:'800'},tabLabel:{fontSize:10,color:C.tabInactive,fontWeight:'700'},
  login:{flex:1,backgroundColor:C.navy,justifyContent:'center',padding:22,gap:16},logo:{width:66,height:66,borderRadius:21,backgroundColor:C.pink,alignItems:'center',justifyContent:'center',alignSelf:'center',shadowColor:'#000',shadowOpacity:.2,shadowRadius:12,elevation:4},logoText:{fontSize:35,fontWeight:'900',color:'#FFF'},brand:{fontSize:27,fontWeight:'900',color:'#FFF',textAlign:'center',letterSpacing:-.6},tagline:{fontSize:13,color:'#B8C9D8',textAlign:'center',marginBottom:10},footer:{fontSize:11,color:'#9BB0C2',textAlign:'center'},
  label:{fontSize:12,color:C.muted,fontWeight:'800',marginTop:4},input:{borderWidth:1,borderColor:C.border,borderRadius:12,padding:12,color:C.text,backgroundColor:C.inputBg,fontSize:14},searchInput:{borderWidth:1,borderColor:C.border,borderRadius:13,paddingHorizontal:14,paddingVertical:12,color:C.text,backgroundColor:C.searchBg,fontSize:13},
  link:{color:C.blue,fontWeight:'900',marginTop:8},row:{flexDirection:'row',gap:8,alignItems:'center'},listLine:{fontSize:13,color:C.text,paddingVertical:7,borderBottomWidth:1,borderColor:C.line},
  projectCardTop:{flexDirection:'row',alignItems:'center',gap:11},projectGlyph:{width:40,height:40,borderRadius:13,backgroundColor:C.glyphBg,alignItems:'center',justifyContent:'center'},projectGlyphText:{fontSize:19,color:C.blue,fontWeight:'900'},chevron:{fontSize:25,color:'#91A2B1',fontWeight:'300'},statusPill:{alignSelf:'flex-start',backgroundColor:C.statusBg,paddingHorizontal:9,paddingVertical:5,borderRadius:20},statusPillText:{fontSize:10,color:C.statusText,fontWeight:'800',textTransform:'capitalize'},
  weekTotal:{backgroundColor:C.weekBg,borderRadius:15,padding:16,alignItems:'center',gap:3},weekTotalLabel:{fontSize:9,color:C.blue,fontWeight:'900',letterSpacing:1.2},weekTotalValue:{fontSize:34,color:C.heading,fontWeight:'900',letterSpacing:-1},
  themeOption:{flexDirection:'row',alignItems:'center',gap:12,padding:13,borderRadius:13,borderWidth:1,borderColor:C.border,backgroundColor:C.card},swatchRow:{flexDirection:'row',gap:3,marginRight:1},swatch:{width:9,height:32,borderRadius:5},themeOptionActive:{borderColor:C.blue,backgroundColor:C.accentBg},themeOptionTitle:{fontSize:14,fontWeight:'900',color:C.text},themeOptionDescription:{fontSize:11,color:C.muted},themeRadio:{width:21,height:21,borderRadius:11,borderWidth:2,borderColor:C.muted,alignItems:'center',justifyContent:'center'},themeRadioActive:{borderColor:C.blue},themeRadioDot:{width:10,height:10,borderRadius:5,backgroundColor:C.blue}
});
s = createStyles(C);
