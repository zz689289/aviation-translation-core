# Read-only process/window diagnostics. No input injection, focus changes or UIA.
Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class WindowEvidence { public long Hwnd; public uint ProcessNumber; public string Class; public string Title; public bool Visible; public string[] Text; }
public static class WordNative {
 public delegate bool EnumProc(IntPtr h, IntPtr p);
 [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc f, IntPtr p);
 [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr h, EnumProc f, IntPtr p);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint n);
 [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr h,StringBuilder s,int n);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int GetClassName(IntPtr h,StringBuilder s,int n);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern IntPtr SendMessageTimeout(IntPtr h,uint m,UIntPtr w,StringBuilder l,uint flags,uint timeout,out UIntPtr result);
 static string Title(IntPtr h) { var s=new StringBuilder(4096); GetWindowText(h,s,s.Capacity); return s.ToString(); }
 static string ClassName(IntPtr h) { var s=new StringBuilder(256); GetClassName(h,s,s.Capacity); return s.ToString(); }
 public static uint ProcessOf(long h) { uint n; GetWindowThreadProcessId(new IntPtr(h),out n); return n; }
 public static WindowEvidence[] Windows(uint number) {
  var rows=new List<WindowEvidence>();
  EnumWindows((h,p)=>{uint n;GetWindowThreadProcessId(h,out n);if(n!=number)return true;
   string c=ClassName(h);var texts=new List<string>();
   if(c=="#32770" || c.StartsWith("bosa_sdm")) EnumChildWindows(h,(ch,cp)=>{var b=new StringBuilder(4096); UIntPtr result; SendMessageTimeout(ch,13,new UIntPtr(4096),b,2,100,out result); if(b.Length>0)texts.Add(b.ToString());return true;},IntPtr.Zero);
   rows.Add(new WindowEvidence{Hwnd=h.ToInt64(),ProcessNumber=n,Class=c,Title=Title(h),Visible=IsWindowVisible(h),Text=texts.ToArray()});return true;},IntPtr.Zero);
  return rows.ToArray();
 }
}
'@
