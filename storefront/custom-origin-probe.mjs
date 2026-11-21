/* Separate, read-only Render service probe for the purchased custom domain.
 * Never forwards cookies, tokens or user data across origins.
 * The shared navigation shell itself has no network side effects. */
export async function isPythonBackend() {
  try {
    const response = await fetch('/api/health',{
      method:'GET',cache:'no-store',credentials:'omit',
      headers:{Accept:'application/json'}
    });
    if(!response.ok || !response.headers.get('content-type')?.includes('application/json'))
      return false;
    const payload=await response.json();
    return payload?.service==='vainahvpn-api' && payload.ok===true;
  }catch{return false;}
}
