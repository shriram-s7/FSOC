/* FSOC-PAT — live camera feed display over WebSocket. */

class CameraFeed {
  constructor(imgElement) {
    this.img = imgElement;
    this.ws = null;
    this._closedByUser = false;
  }

  start() {
    this._closedByUser = false;
    this.ws = API.connectFrameWS((base64Frame,telemetry) => {
      if (this.img) {
        // Decode offscreen; only publish image and its matching state together.
        if(this._decoding)return;
        this._decoding=true;
        const next=new Image();
        next.onload=()=>{this._decoding=false;if(this._closedByUser)return;this.img._frameState=telemetry;this.img.src=next.src;};
        next.onerror=()=>{this._decoding=false;};next.src=`data:image/jpeg;base64,${base64Frame}`;
      }
    });
  }

  stop() {
    this._closedByUser = true;
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.close();
      this.ws = null;
    }
  }
}
