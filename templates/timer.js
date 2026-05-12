export function setLogoutAt(unixMs){
  try{ sessionStorage.setItem('token_exp_timer_until', JSON.stringify(unixMs)); }catch(e){}
}


